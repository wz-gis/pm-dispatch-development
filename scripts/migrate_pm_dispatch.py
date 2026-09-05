#!/usr/bin/env python3
"""Migrate embedded Tasks to Task v4/Runtime v1 and Evidence to v2."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_pm_dispatch import (  # noqa: E402
    EVIDENCE_REQUIRED_STATUSES,
    assert_supported_schema,
    compose_task_runtime,
    design_freeze_fingerprint,
    load_adapters,
    load_structured_file,
    parse_time,
    runtime_file_for,
    validate_adapter_resolution,
    validate_schema,
    validate_task_runtime_layout,
)
from wait_policy import (  # noqa: E402
    CODEX_WAIT_POLICY_ADAPTER_VERSION,
    new_wait_budget,
)
from monitor_policy import (  # noqa: E402
    CODEX_INSPECTION_POLICY_ADAPTER_VERSION,
    PROVISIONING_DEFAULT_TTL_SECONDS,
    new_inspection_budget,
)


LEGACY_ID_RE = re.compile(
    r"^(bug|spec|onboard|release|env|chore)[-_ ]?(\d{3})(?:[-_ ].*)?$", re.IGNORECASE
)
PROFILE_BY_DIFFICULTY = {
    "trivial": "fast",
    "simple": "fast",
    "normal": "standard",
    "hard": "deep",
    "critical": "critical",
}
GATE_SLUG = {
    "contract": "contract",
    "implementation": "impl",
    "integration": "integration",
    "verification": "verify",
    "closure": "closure",
}
ARTIFACT_KIND_BY_GROUP = {
    "api": "api",
    "sql": "sql",
    "browser": "browser",
    "screenshots": "screenshot",
    "logs": "log",
    "ids": "id",
    "upgrade_path": "upgrade_path",
    "release_path": "release_path",
}
ARTIFACT_GROUPS = [
    "commands",
    "commits",
    "files_changed",
    "api",
    "sql",
    "browser",
    "screenshots",
    "logs",
    "ids",
    "upgrade_path",
    "release_path",
]

DEFAULT_AUTONOMY_POLICY = {
    "default_action": "proceed",
    "clarification_policy": "material-irreversible-only",
    "blocker_policy": "hard-only",
    "verification_policy": "risk-scaled",
    "recovery": {
        "same_method_retries": 1,
        "alternate_method_attempts": 2,
        "rediscovery_limit": 1,
    },
}

BLOCKER_CAUSE_BY_TYPE = {
    "environment": "external-unavailable",
    "contract": "irreversible-contract",
    "thread": "external-unavailable",
    "pm": "human-authorization",
    "dependency": "dependency",
    "resource": "resource-conflict",
}


class MigrationError(ValueError):
    """Raised before source files are changed when migration cannot be proven safe."""


def normalize_task_id(value: Any) -> str:
    text = str(value or "")
    if re.fullmatch(r"(BUG|SPEC|ONBOARD|RELEASE|ENV|CHORE)-\d{3}", text):
        return text
    match = LEGACY_ID_RE.fullmatch(text)
    if not match:
        return text
    return f"{match.group(1).upper()}-{match.group(2)}"


def migrate_task(
    source: dict[str, Any], adapters: dict[str, dict[str, Any]], now: str
) -> dict[str, Any]:
    task = copy.deepcopy(source)
    if task.get("schema_version") == "3":
        task = normalize_model_routes(task, adapters, now)
        return normalize_dispatch_efficiency_contract(task, now)

    task["schema_version"] = "3"
    task["id"] = normalize_task_id(task.get("id"))
    area = "/".join(str(item) for item in task.get("area", []))
    if task.get("id") and task.get("priority") and area and task.get("title"):
        task["display_name"] = f"{task['id']} {task['priority']} {area} {task['title']}"
    migrate_task_references(task)

    dispatch = task.setdefault("dispatch", {})
    strategy = dispatch.get("strategy", "direct")
    old_provider = dispatch.pop("provider", None)
    old_policy = dispatch.pop("model_policy", None) or {}
    old_request = dispatch.pop("model_request", None) or {}
    old_resolution = dispatch.get("resolution") or {}
    old_fallback = dispatch.get("fallback_policy") or {}
    if strategy == "direct":
        dispatch.update(
            {
                "provider_policy": {"mode": "local", "provider": "local"},
                "required_capabilities": [],
                "required_evidence_kinds": [],
                "reasoning_profile": None,
                "fallback_policy": None,
                "resolution": None,
            }
        )
    else:
        provider = str(
            old_provider
            or old_resolution.get("provider")
            or (dispatch.get("provider_policy") or {}).get("provider")
            or "codex"
        )
        adapter = adapters.get(provider)
        if not adapter:
            raise MigrationError(f"worker task uses unknown provider {provider!r}")
        profile = (
            old_request.get("reasoning_profile")
            or old_resolution.get("reasoning_profile")
            or PROFILE_BY_DIFFICULTY.get(old_policy.get("difficulty"))
            or "standard"
        )
        model_route = adapter.get("components", {}).get("model", {}).get("profiles", {}).get(profile)
        model_id = model_route.get("model_id") if model_route else None
        adapter_effort = (
            adapter.get("components", {})
            .get("reasoning", {})
            .get("profiles", {})
            .get(profile)
        )
        provider_effort = (
            model_route.get("reasoning_effort")
            if model_route
            else (
                adapter_effort
                or old_policy.get("reasoning_effort")
                or old_resolution.get("provider_reasoning_effort")
                or profile
            )
        )
        heartbeat_required = bool(dispatch.get("heartbeat_required"))
        required_capabilities = list(dispatch.get("required_capabilities") or ["background-worker"])
        if heartbeat_required and "heartbeat" not in required_capabilities:
            required_capabilities.append("heartbeat")
        available_evidence = adapter.get("components", {}).get("evidence", {}).get(
            "artifact_kinds", []
        )
        required_evidence = list(dispatch.get("required_evidence_kinds") or [])
        if not required_evidence:
            required_evidence = [kind for kind in ("command", "log") if kind in available_evidence]
        monitor_modes = adapter.get("components", {}).get("monitor", {}).get("modes", [])
        has_heartbeat = isinstance(dispatch.get("heartbeat"), dict)
        monitor_mode = (
            "heartbeat"
            if heartbeat_required and has_heartbeat and "heartbeat" in monitor_modes
            else None
        )
        if not monitor_mode:
            monitor_mode = "event-lease" if heartbeat_required and "event-lease" in monitor_modes else None
        if not monitor_mode:
            monitor_mode = "milestone" if heartbeat_required and "milestone" in monitor_modes else None
        if not monitor_mode:
            monitor_mode = "heartbeat" if heartbeat_required and "heartbeat" in monitor_modes else None
        if not monitor_mode:
            monitor_mode = next(
                (mode for mode in ("event-lease", "milestone", "poll", "manual", "heartbeat") if mode in monitor_modes),
                "manual",
            )
        resolved_capabilities = set(required_capabilities)
        if monitor_mode in {"milestone", "event-lease"}:
            resolved_capabilities.discard("heartbeat")
            if "milestone-notify" in adapter.get("capabilities", []):
                resolved_capabilities.add("milestone-notify")
        if monitor_mode == "event-lease":
            resolved_capabilities.update({"lease-watchdog", "terminal-event-wait"})
        resolution = {
            "provider": provider,
            "adapter_version": str(adapter.get("adapter_version", "0")),
            "model_id": model_id,
            "reasoning_profile": profile,
            "provider_reasoning_effort": provider_effort,
            "worker_type": (adapter.get("worker_types") or ["agent-thread"])[0],
            "monitor_mode": monitor_mode,
            "capabilities": sorted(resolved_capabilities),
            "evidence_kinds": sorted(set(required_evidence)),
            "resolved_at": dispatch.get("selected_at") or now,
            "reason": (
                old_policy.get("reason")
                or old_resolution.get("reason")
                or "migrated with provider reasoning and inherited/default model policy"
            ),
        }
        provider_policy = dispatch.get("provider_policy") or {
            "mode": "pinned",
            "provider": provider,
        }
        fallback_policy = {
            "mode": old_fallback.get("mode") or "strict",
            "allowed_providers": old_fallback.get("allowed_providers") or [provider],
            "allow_manual_monitoring": bool(
                old_fallback.get("allow_manual_monitoring", False)
            ),
        }
        dispatch.update(
            {
                "provider_policy": provider_policy,
                "required_capabilities": sorted(set(required_capabilities)),
                "required_evidence_kinds": sorted(set(required_evidence)),
                "reasoning_profile": profile,
                "fallback_policy": fallback_policy,
                "resolution": resolution,
            }
        )

        run_id_map: dict[str, str] = {}
        for index, run in enumerate(task.get("runs", []), start=1):
            old_run_id = str(run.get("run_id") or "")
            migrate_run_identity(run, task, index)
            run_id_map[old_run_id] = run["run_id"]
            run["provider"] = provider
            run["adapter_version"] = resolution["adapter_version"]
            run["model_id"] = resolution["model_id"]
            run.pop("selected_model", None)
            run["reasoning_profile"] = resolution["reasoning_profile"]
            run.pop("reasoning_effort", None)
            run["provider_reasoning_effort"] = resolution["provider_reasoning_effort"]
            run["resolution_reason"] = (
                run.pop("model_reason", None) or resolution["reason"]
            )
            run.pop("model_tier", None)
            if (
                provider == "codex"
                and int(resolution["adapter_version"]) >= CODEX_WAIT_POLICY_ADAPTER_VERSION
                and run.get("status") in {"provisioning", "queued", "running"}
            ):
                run.setdefault("wait_budget", new_wait_budget(now))
            if (
                provider == "codex"
                and int(resolution["adapter_version"])
                >= CODEX_INSPECTION_POLICY_ADAPTER_VERSION
                and run.get("status") in {"provisioning", "queued", "running"}
            ):
                run.setdefault("inspection_budget", new_inspection_budget(now))
        for lock in task.get("resources", {}).get("locks", []):
            holder = str(lock.get("holder_run_id") or "")
            if holder in run_id_map:
                lock["holder_run_id"] = run_id_map[holder]

    dispatch.setdefault("reason", "migrated dispatch")
    dispatch.setdefault("worker_required", strategy != "direct")
    dispatch.setdefault("heartbeat_required", False)
    dispatch.setdefault("selected_at", now)
    dispatch.setdefault("max_parallel_workers", None if strategy == "direct" else 1)
    normalize_dispatch_efficiency_contract(task, now)
    dispatch.setdefault("batch", None)
    dispatch.setdefault("heartbeat", None)
    dispatch.setdefault("escalation_triggers", [])
    return task


def normalize_dispatch_efficiency_contract(
    task: dict[str, Any], now: str
) -> dict[str, Any]:
    """Backfill autonomy, design, and monitor fields without inventing runtime state."""
    dispatch = task.setdefault("dispatch", {})
    task.setdefault("quality_checks", {"policy": "risk-scaled", "checks": []})
    dispatch.setdefault("autonomy_policy", copy.deepcopy(DEFAULT_AUTONOMY_POLICY))
    normalize_blockers(task)
    if (dispatch.get("resolution") or {}).get("monitor_mode") in {"milestone", "event-lease"}:
        dispatch["heartbeat"] = None
    if dispatch.get("strategy") == "direct":
        dispatch["design_freeze"] = None
        dispatch["worker_reuse"] = None
        return task

    strategy = dispatch.get("strategy")
    if strategy in {"single-worker", "batch-worker"}:
        dispatch["worker_reuse"] = {
            "mode": "sticky",
            "reuse_across_gates": True,
            "max_runs_per_worker": 6,
            "replacement_triggers": [
                "irrecoverable-worker",
                "safety-boundary-change",
                "design-freeze-change",
                "provider-change",
                "context-saturated",
                "independent-review",
            ],
        }
    else:
        dispatch["worker_reuse"] = {
            "mode": "isolated",
            "reuse_across_gates": False,
            "max_runs_per_worker": 1,
            "replacement_triggers": [
                "irrecoverable-worker",
                "safety-boundary-change",
                "design-freeze-change",
                "provider-change",
                "context-saturated",
                "independent-review",
            ],
        }

    freeze = dispatch.get("design_freeze")
    if not isinstance(freeze, dict):
        required_levels = task.get("verification", {}).get("required_levels") or []
        freeze = {
            "status": "frozen",
            "frozen_at": dispatch.get("selected_at") or now,
            "scope": list(task.get("area") or ["legacy-task-scope"]),
            "constraints": [
                "Preserve the accepted scope and existing behavior recorded by the task."
            ],
            "acceptance": (
                [f"Satisfy {level} with structured evidence." for level in required_levels]
                or ["Satisfy the task verification policy with structured evidence."]
            ),
            "fingerprint": None,
            "change_policy": "material-only-new-attempt",
        }
        freeze["fingerprint"] = design_freeze_fingerprint(freeze)
        dispatch["design_freeze"] = freeze
    elif freeze.get("change_policy") != "material-only-new-attempt":
        freeze["change_policy"] = "material-only-new-attempt"
        freeze["fingerprint"] = design_freeze_fingerprint(freeze)

    fingerprint = freeze.get("fingerprint")
    previous_worker_id: str | None = None
    for run in task.get("runs", []):
        worker_id = run.get("worker_id")
        if "worker_replacement_reason" not in run:
            run["worker_replacement_reason"] = (
                "legacy-history"
                if previous_worker_id and worker_id and worker_id != previous_worker_id
                else None
            )
        if worker_id:
            previous_worker_id = str(worker_id)
        if run.get("status") in {"provisioning", "queued", "running"}:
            run["design_fingerprint"] = fingerprint
        else:
            run.setdefault("design_fingerprint", fingerprint)
        for attempt in run.get("attempts", []):
            lease = attempt.get("lease")
            if not isinstance(lease, dict):
                continue
            checkpoint_at = lease.get("heartbeat_at") or lease.get("acquired_at") or now
            lease.setdefault("heartbeat_at", checkpoint_at)
            lease.setdefault("progress_seq", 0)
            lease.setdefault("last_progress_at", checkpoint_at)
            lease.setdefault("last_progress_summary", "migrated lease; progress unknown")
            lease.setdefault("event_cursor", None)
            lease.setdefault("liveness_state", "live")
            lease.setdefault("monitor_gap_started_at", None)
            lease.setdefault("disconnect_probe_count", 0)
            lease.setdefault("disconnect_first_seen_at", None)

    heartbeat = dispatch.get("heartbeat")
    if isinstance(heartbeat, dict):
        active_runs = [
            run
            for run in task.get("runs", [])
            if run.get("status") in {"provisioning", "queued", "running"}
        ]
        coordinator_thread_id = heartbeat.get("coordinator_thread_id")
        if (
            not isinstance(coordinator_thread_id, str)
            or not coordinator_thread_id.strip()
        ) and heartbeat.get("status") in {"paused", "stopped"}:
            heartbeat["coordinator_thread_id"] = (
                f"legacy-coordinator:{task.get('id', 'unknown')}"
            )
        heartbeat.pop("monitor_thread_id", None)
        heartbeat.setdefault(
            "target_run_id",
            active_runs[0].get("run_id") if active_runs else (task.get("runs") or [{}])[-1].get("run_id"),
        )
        heartbeat["context_policy"] = "coordinator"
        heartbeat["scan_scope"] = "incremental"
        heartbeat["read_set"] = ["worker-status", "lease", "latest-milestone"]
        heartbeat["full_scan_triggers"] = [
            "milestone",
            "terminal",
            "safety-boundary-change",
            "design-freeze-change",
        ]
        heartbeat.setdefault("prompt_max_chars", 220)
        heartbeat["interval_minutes"] = 10
        heartbeat["lightweight"] = True
        heartbeat.setdefault("coordinator_epoch", 1)
    return task


def normalize_blockers(task: dict[str, Any]) -> None:
    """Backfill legacy blocker classification without fabricating recovery attempts."""
    for blocker in task.get("blockers", []):
        blocker.setdefault("hard", blocker.get("status") == "open")
        blocker.setdefault(
            "cause",
            BLOCKER_CAUSE_BY_TYPE.get(str(blocker.get("type")), "external-unavailable"),
        )
        blocker.setdefault("recovery_attempts", 0)
        blocker.setdefault(
            "next_unblock_action",
            blocker.get("resolution") or blocker.get("description") or "Review blocker",
        )


def normalize_model_routes(
    task: dict[str, Any], adapters: dict[str, dict[str, Any]], now: str
) -> dict[str, Any]:
    """Normalize current Provider reasoning/model policy in an already-v3 Task."""
    dispatch = task.get("dispatch") or {}
    resolution = dispatch.get("resolution")
    if dispatch.get("strategy") == "direct" or not isinstance(resolution, dict):
        return task
    provider = resolution.get("provider")
    adapter = adapters.get(str(provider))
    if not adapter:
        raise MigrationError(f"worker task uses unknown provider {provider!r}")
    profile = resolution.get("reasoning_profile") or dispatch.get("reasoning_profile")
    model_route = adapter.get("components", {}).get("model", {}).get("profiles", {}).get(profile)
    if model_route:
        resolution["model_id"] = model_route["model_id"]
        resolution["provider_reasoning_effort"] = model_route["reasoning_effort"]
    else:
        resolution["model_id"] = None
        resolution["provider_reasoning_effort"] = (
            adapter.get("components", {})
            .get("reasoning", {})
            .get("profiles", {})
            .get(profile)
        )
    resolution["adapter_version"] = str(adapter.get("adapter_version", "0"))
    monitor_modes = adapter.get("components", {}).get("monitor", {}).get("modes", [])
    if dispatch.get("heartbeat_required") and isinstance(dispatch.get("heartbeat"), dict) and "heartbeat" in monitor_modes:
        resolution["monitor_mode"] = "heartbeat"
        capabilities = set(resolution.get("capabilities") or [])
        capabilities.add("heartbeat")
        resolution["capabilities"] = sorted(capabilities)
    for run in task.get("runs", []):
        if run.get("status") in {"provisioning", "queued", "running"}:
            run["adapter_version"] = resolution["adapter_version"]
            run["model_id"] = resolution.get("model_id")
            run["provider_reasoning_effort"] = resolution["provider_reasoning_effort"]
            if (
                provider == "codex"
                and int(resolution["adapter_version"]) >= CODEX_WAIT_POLICY_ADAPTER_VERSION
            ):
                run.setdefault("wait_budget", new_wait_budget(now))
            if (
                provider == "codex"
                and int(resolution["adapter_version"])
                >= CODEX_INSPECTION_POLICY_ADAPTER_VERSION
            ):
                run.setdefault("inspection_budget", new_inspection_budget(now))
        else:
            run.setdefault("model_id", resolution.get("model_id"))
    return task


def normalize_runtime_routes(
    task: dict[str, Any],
    runtime: dict[str, Any],
    adapters: dict[str, dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    """Upgrade only active Runtime facts; terminal Runs preserve history."""
    resolution = runtime.get("resolution")
    if task.get("dispatch", {}).get("strategy") == "direct" or not isinstance(resolution, dict):
        return runtime
    active_runs = [
        run
        for run in runtime.get("runs", [])
        if run.get("status") in {"provisioning", "queued", "running"}
    ]
    if not active_runs and task.get("status") in EVIDENCE_REQUIRED_STATUSES:
        return runtime
    provider = str(resolution.get("provider") or "")
    adapter = adapters.get(provider)
    if not adapter:
        raise MigrationError(f"worker task uses unknown provider {provider!r}")
    profile = resolution.get("reasoning_profile") or task.get("dispatch", {}).get(
        "reasoning_profile"
    )
    model_route = adapter.get("components", {}).get("model", {}).get("profiles", {}).get(profile)
    if model_route:
        resolution["model_id"] = model_route["model_id"]
        resolution["provider_reasoning_effort"] = model_route["reasoning_effort"]
    else:
        resolution["model_id"] = None
        resolution["provider_reasoning_effort"] = (
            adapter.get("components", {})
            .get("reasoning", {})
            .get("profiles", {})
            .get(profile)
        )
    resolution["adapter_version"] = str(adapter.get("adapter_version", "0"))
    for run in active_runs:
        run["adapter_version"] = resolution["adapter_version"]
        run["model_id"] = resolution.get("model_id")
        run["provider_reasoning_effort"] = resolution["provider_reasoning_effort"]
        if (
            provider == "codex"
            and int(resolution["adapter_version"]) >= CODEX_WAIT_POLICY_ADAPTER_VERSION
        ):
            run.setdefault("wait_budget", new_wait_budget(now))
        if (
            provider == "codex"
            and int(resolution["adapter_version"])
            >= CODEX_INSPECTION_POLICY_ADAPTER_VERSION
        ):
            run.setdefault("inspection_budget", new_inspection_budget(now))
    normalize_provisioning_runs(runtime, now)
    heartbeat = runtime.get("heartbeat")
    if isinstance(heartbeat, dict):
        heartbeat.setdefault("coordinator_epoch", 1)
    return runtime


def normalize_provisioning_runs(runtime: dict[str, Any], now: str) -> None:
    """Turn an incomplete Worker create into a bounded provisioning transaction."""
    current = parse_time(now)
    deadline = (current + timedelta(seconds=PROVISIONING_DEFAULT_TTL_SECONDS)).isoformat().replace(
        "+00:00", "Z"
    )
    provisioning_ids: set[str] = set()
    for run in runtime.get("runs", []):
        if run.get("status") != "queued" or run.get("worker_id"):
            continue
        attempts = [item for item in run.get("attempts", []) if isinstance(item, dict)]
        if len(attempts) != 1 or attempts[0].get("lease") is not None:
            continue
        run["status"] = "provisioning"
        run["last_operation"] = "provision"
        attempts[0]["status"] = "provisioning"
        attempts[0]["finished_at"] = None
        transaction_id = f"provision-{run.get('run_id')}"
        run["provisioning"] = {
            "transaction_id": transaction_id,
            "status": "pending",
            "started_at": now,
            "deadline_at": deadline,
            "finished_at": None,
            "failure": None,
        }
        provisioning_ids.add(str(run.get("run_id") or ""))
    for lock in runtime.get("resources", {}).get("locks", []):
        if (
            lock.get("status") == "active"
            and str(lock.get("holder_run_id") or "") in provisioning_ids
        ):
            lock["lease_expires_at"] = deadline


def migrate_task_references(task: dict[str, Any]) -> None:
    dependencies = task.get("dependencies", {})
    for dependency in dependencies.get("requires", []):
        dependency["task_id"] = normalize_task_id(dependency.get("task_id"))
    dependencies["blocks"] = [normalize_task_id(item) for item in dependencies.get("blocks", [])]
    batch = task.get("dispatch", {}).get("batch")
    if batch:
        batch["task_ids"] = [normalize_task_id(item) for item in batch.get("task_ids", [])]


def migrate_run_identity(run: dict[str, Any], task: dict[str, Any], index: int) -> None:
    old_worker_name = str(run.get("worker_name") or "")
    if old_worker_name.startswith("BATCH-"):
        worker_name = old_worker_name
    else:
        number_match = re.search(r"-w(\d+)$", old_worker_name)
        worker_number = int(number_match.group(1)) if number_match else index
        role = GATE_SLUG.get(str(run.get("gate")), "impl")
        worker_name = f"{task['id']}-{role}-w{worker_number:02d}"
        run["worker_label"] = f"{task['display_name']} [{role} w{worker_number:02d}]"
    run["worker_name"] = worker_name
    run["run_id"] = f"run-{worker_name}"
    for attempt_index, attempt in enumerate(run.get("attempts", []), start=1):
        old_attempt_id = str(attempt.get("attempt_id") or "")
        number_match = re.search(r"-a(\d+)$", old_attempt_id)
        attempt_number = int(number_match.group(1)) if number_match else attempt_index
        attempt["attempt_id"] = f"attempt-{worker_name}-a{attempt_number:02d}"
        lease = attempt.get("lease")
        if lease:
            lease["holder"] = run["run_id"]


def migrate_evidence(source: dict[str, Any], now: str) -> dict[str, Any]:
    evidence = copy.deepcopy(source)
    if evidence.get("schema_version") == "2":
        evidence.setdefault("quality_checks", [])
        return evidence

    evidence["schema_version"] = "2"
    evidence["task_id"] = normalize_task_id(evidence.get("task_id"))
    evidence.setdefault("generated_at", now)
    verification = evidence.setdefault("verification", {})
    verification.setdefault("changed_surface", [])
    verification.setdefault("original_user_path", "legacy evidence; recapture required")
    verification.setdefault("runtime_shape", "mock")
    verification.setdefault("test_data", [])
    verification.setdefault("levels", {})
    verification.setdefault("existing_data_regression", "not verified")
    verification.setdefault("uncovered_items", ["legacy evidence requires structured recapture"])
    evidence.setdefault("quality_checks", [])

    artifacts = evidence.setdefault("artifacts", {})
    for group in ARTIFACT_GROUPS:
        values = artifacts.setdefault(group, [])
        if group in {"commits", "files_changed"}:
            continue
        artifacts[group] = [
            migrate_artifact(group, item, index, evidence["generated_at"])
            for index, item in enumerate(values, start=1)
        ]
    evidence.setdefault("runs", [])
    evidence.setdefault("blockers", [])
    evidence.setdefault(
        "conclusion",
        {
            "status": "PARTIAL_VERIFIED",
            "evidence_level": "NONE",
            "mock_based": False,
            "real_chain_verified": False,
            "accepted_fallback": None,
            "notes": "Migrated legacy evidence; recapture before terminal closure.",
        },
    )
    return evidence


def split_task_runtime(
    source: dict[str, Any], now: str, runtime_file: str = "runtime.yaml"
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a normalized embedded Task v3 into Task v4 and Runtime v1."""
    if source.get("schema_version") != "3":
        raise MigrationError("runtime split requires a normalized Task v3")
    task = copy.deepcopy(source)
    dispatch = task.setdefault("dispatch", {})
    resolution = dispatch.pop("resolution", None)
    selected_at = dispatch.pop("selected_at", None)
    heartbeat = dispatch.pop("heartbeat", None)
    resources = task.pop("resources", {"locks": []})
    runs = task.pop("runs", [])
    for run in runs:
        run.setdefault("continuation_token", None)
        run.setdefault("event_cursor", None)
        run.setdefault("last_operation", None)
        run.setdefault("last_idempotency_key", None)
    task["schema_version"] = "4"
    task["runtime_file"] = runtime_file
    runtime = {
        "schema_version": "1",
        "task_id": task.get("id"),
        "task_schema_version": "4",
        "resolution": resolution,
        "selected_at": selected_at,
        "heartbeat": heartbeat,
        "resources": resources,
        "runs": runs,
        "event_log_file": "events.jsonl",
        "last_updated": source.get("last_updated") or now,
    }
    normalize_provisioning_runs(runtime, now)
    return task, runtime


def migrate_artifact(group: str, item: Any, index: int, captured_at: str) -> dict[str, Any]:
    existing = item if isinstance(item, dict) else {}
    slug = group.rstrip("s").replace("_", "-")
    generated_id = f"legacy-{slug}-{index:03d}"
    candidate_id = str(existing.get("artifact_id") or "")
    artifact_id = (
        candidate_id
        if re.fullmatch(r"[a-z][a-z0-9-]*", candidate_id)
        else generated_id
    )
    subject = str(existing.get("subject") or item or "legacy artifact")
    source = str(existing.get("source") or "legacy-migration")
    evidence_ref = str(existing.get("evidence_ref") or f"legacy/{artifact_id}.txt")
    artifact_time = str(existing.get("captured_at") or captured_at)
    try:
        parse_time(artifact_time)
    except (TypeError, ValueError):
        artifact_time = captured_at
    complete = isinstance(item, dict) and all(
        existing.get(key)
        for key in ("artifact_id", "kind", "source", "subject", "result", "captured_at", "evidence_ref")
    )
    result = existing.get("result") if complete else "info"
    if result not in {"pass", "fail", "info"}:
        result = "info"
    if group == "commands":
        command = str(existing.get("command") or item or "legacy command")
        exit_code = existing.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            exit_code = -1
            result = "info"
        if result == "pass" and exit_code != 0:
            result = "info"
        return {
            "artifact_id": artifact_id,
            "kind": "command",
            "source": source,
            "subject": subject,
            "result": result,
            "captured_at": artifact_time,
            "evidence_ref": evidence_ref,
            "command": command,
            "exit_code": exit_code,
        }
    artifact = {
        "artifact_id": artifact_id,
        "kind": ARTIFACT_KIND_BY_GROUP[group],
        "source": source,
        "subject": subject,
        "result": result,
        "captured_at": artifact_time,
        "evidence_ref": evidence_ref,
    }
    if "status_code" in existing and (
        existing["status_code"] is None or isinstance(existing["status_code"], int)
    ):
        artifact["status_code"] = existing["status_code"]
    if "digest" in existing and (
        existing["digest"] is None or isinstance(existing["digest"], str)
    ):
        artifact["digest"] = existing["digest"]
    if group == "api" and result == "pass" and artifact.get("status_code") is None:
        artifact["result"] = "info"
    return artifact


def collect_paths(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in inputs:
        path = Path(value).resolve()
        if path.is_dir():
            paths.extend(sorted(path.glob("*/task.yaml")))
            paths.extend(sorted(path.glob("*/evidence.yaml")))
        else:
            paths.append(path)
    return paths


def validate_migrated_document(
    document: dict[str, Any],
    document_type: str,
    task_schema: dict[str, Any],
    evidence_schema: dict[str, Any],
    adapters: dict[str, dict[str, Any]],
    prefix: str,
) -> list[str]:
    schema = task_schema if document_type == "task" else evidence_schema
    errors = validate_schema(document, schema, prefix, schema)
    if document_type == "task" and not errors and document.get("dispatch", {}).get("resolution"):
        validate_adapter_resolution(document, adapters, errors, prefix)
    return errors


def validate_migrated_task_bundle(
    task: dict[str, Any],
    runtime: dict[str, Any],
    task_schema: dict[str, Any],
    runtime_schema: dict[str, Any],
    adapters: dict[str, dict[str, Any]],
    prefix: str,
) -> list[str]:
    errors = validate_schema(task, task_schema, prefix, task_schema)
    errors.extend(
        validate_schema(runtime, runtime_schema, f"{prefix}:runtime", runtime_schema)
    )
    errors.extend(validate_task_runtime_layout(task, runtime, prefix))
    if not errors and runtime.get("resolution"):
        validate_adapter_resolution(
            compose_task_runtime(task, runtime), adapters, errors, prefix
        )
    return errors


def atomic_write_with_backup(path: Path, rendered: str, source_version: str = "1") -> Path:
    version = source_version if re.fullmatch(r"[0-9]+", source_version) else "legacy"
    backup = path.with_suffix(path.suffix + f".v{version}.bak")
    if backup.exists():
        raise MigrationError(f"backup already exists: {backup}")
    temporary = path.with_name(f".{path.name}.migrating")
    shutil.copy2(path, backup)
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return backup


def atomic_write_new(path: Path, rendered: str) -> None:
    if path.exists():
        raise MigrationError(f"refusing to overwrite existing sidecar: {path}")
    temporary = path.with_name(f".{path.name}.migrating")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate Task to v4/Runtime v1 and Evidence to v2."
    )
    parser.add_argument("paths", nargs="+", help="Task/Evidence files or a docs/tasks directory")
    parser.add_argument("--adapter-dir", help="Directory containing *.adapter.json")
    parser.add_argument("--now", help="Migration timestamp in ISO-8601")
    parser.add_argument("--write", action="store_true", help="Write migrated JSON-compatible YAML in place")
    args = parser.parse_args()

    root = SCRIPT_DIR.parent
    adapter_dir = Path(args.adapter_dir).resolve() if args.adapter_dir else root / "references" / "adapters"
    schema_dir = root / "references" / "schemas"
    task_schema = load_structured_file(schema_dir / "task.schema.json")
    evidence_schema = load_structured_file(schema_dir / "evidence.schema.json")
    runtime_schema = load_structured_file(schema_dir / "runtime.schema.json")
    adapter_schema = load_structured_file(schema_dir / "adapter.schema.json")
    for name, schema in (
        ("task.schema.json", task_schema),
        ("evidence.schema.json", evidence_schema),
        ("runtime.schema.json", runtime_schema),
        ("adapter.schema.json", adapter_schema),
    ):
        assert_supported_schema(schema, name)
    adapter_catalog, adapter_errors = load_adapters(adapter_dir, adapter_schema)
    if adapter_errors:
        raise MigrationError("invalid adapter catalog: " + "; ".join(adapter_errors))
    now = args.now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    pending: list[dict[str, Any]] = []
    for path in collect_paths(args.paths):
        document = load_structured_file(path)
        source_version = str(document.get("schema_version") or "1")
        if "dispatch" in document or "id" in document:
            creating_runtime = document.get("schema_version") != "4"
            if document.get("schema_version") == "4":
                migrated_task = copy.deepcopy(document)
                runtime_path = runtime_file_for(path, migrated_task, None)
                if runtime_path is None or not runtime_path.exists():
                    raise MigrationError(f"{path}: Task v4 Runtime sidecar is missing")
                runtime = load_structured_file(runtime_path)
                original_runtime = copy.deepcopy(runtime)
                runtime = normalize_runtime_routes(
                    migrated_task,
                    runtime,
                    adapter_catalog,
                    now,
                )
            else:
                embedded = migrate_task(document, adapter_catalog, now)
                migrated_task, runtime = split_task_runtime(embedded, now)
                runtime_path = path.parent / migrated_task["runtime_file"]
                original_runtime = None
                if args.write and runtime_path.exists():
                    raise MigrationError(
                        f"{path}: refusing to replace existing Runtime sidecar {runtime_path}"
                    )
            migration_errors = validate_migrated_task_bundle(
                migrated_task,
                runtime,
                task_schema,
                runtime_schema,
                adapter_catalog,
                str(path),
            )
            if migration_errors:
                raise MigrationError(
                    "migrated output is invalid: " + "; ".join(migration_errors)
                )
            pending.append(
                {
                    "path": path,
                    "rendered": json.dumps(migrated_task, ensure_ascii=False, indent=2) + "\n",
                    "changed": migrated_task != document,
                    "source_version": source_version,
                    "new": False,
                }
            )
            pending.append(
                {
                    "path": runtime_path,
                    "rendered": json.dumps(runtime, ensure_ascii=False, indent=2) + "\n",
                    "changed": not runtime_path.exists() or runtime != original_runtime,
                    "source_version": "1",
                    "new": not runtime_path.exists(),
                }
            )
            event_path = runtime_path.parent / runtime["event_log_file"]
            if creating_runtime and args.write and event_path.exists():
                raise MigrationError(
                    f"{path}: refusing to reuse existing Runtime event log {event_path}"
                )
            if not event_path.exists():
                pending.append(
                    {
                        "path": event_path,
                        "rendered": "",
                        "changed": True,
                        "source_version": "1",
                        "new": True,
                    }
                )
            continue
        if "task_id" in document and "task_schema_version" not in document:
            migrated = migrate_evidence(document, now)
            document_type = "evidence"
        else:
            raise MigrationError(f"{path}: cannot determine Task or Evidence document type")
        migration_errors = validate_migrated_document(
            migrated,
            document_type,
            task_schema,
            evidence_schema,
            adapter_catalog,
            str(path),
        )
        if migration_errors:
            raise MigrationError("migrated output is invalid: " + "; ".join(migration_errors))
        rendered = json.dumps(migrated, ensure_ascii=False, indent=2) + "\n"
        pending.append(
            {
                "path": path,
                "rendered": rendered,
                "changed": migrated != document,
                "source_version": source_version,
                "new": False,
            }
        )

    if not args.write:
        for item in pending:
            print(f"--- {item['path']}")
            print(item["rendered"], end="")
        return 0

    for item in pending:
        path = item["path"]
        if not item["changed"]:
            print(f"unchanged {path}")
            continue
        if item["new"]:
            atomic_write_new(path, item["rendered"])
            print(f"created {path}")
            continue
        backup = atomic_write_with_backup(
            path, item["rendered"], item["source_version"]
        )
        print(f"migrated {path} (backup: {backup})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Migrate legacy PM dispatch Task/Evidence documents to schema version 2."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_adapters,
    load_structured_file,
    parse_time,
    validate_adapter_resolution,
    validate_schema,
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
    if task.get("schema_version") == "2":
        return task

    task["schema_version"] = "2"
    task["id"] = normalize_task_id(task.get("id"))
    area = "/".join(str(item) for item in task.get("area", []))
    if task.get("id") and task.get("priority") and area and task.get("title"):
        task["display_name"] = f"{task['id']} {task['priority']} {area} {task['title']}"
    migrate_task_references(task)

    dispatch = task.setdefault("dispatch", {})
    strategy = dispatch.get("strategy", "direct")
    old_provider = dispatch.pop("provider", None)
    old_policy = dispatch.pop("model_policy", None)
    if strategy == "direct":
        dispatch.update(
            {
                "provider_policy": {"mode": "local", "provider": "local"},
                "required_capabilities": [],
                "required_evidence_kinds": [],
                "model_request": None,
                "fallback_policy": None,
                "resolution": None,
            }
        )
    else:
        provider = str(old_provider or (dispatch.get("resolution") or {}).get("provider") or "codex")
        adapter = adapters.get(provider)
        if not adapter:
            raise MigrationError(f"worker task uses unknown provider {provider!r}")
        policy = old_policy or {}
        profile = PROFILE_BY_DIFFICULTY.get(policy.get("difficulty"), "standard")
        component_model = adapter.get("components", {}).get("model", {})
        model_id = policy.get("selected_model") or component_model.get("default_model") or "unknown-model"
        model = next(
            (item for item in adapter.get("models", []) if item.get("id") == model_id), {}
        )
        provider_effort = (
            policy.get("reasoning_effort")
            or model.get("reasoning_profiles", {}).get(profile)
            or profile
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
        monitor_mode = "heartbeat" if heartbeat_required and "heartbeat" in monitor_modes else None
        if not monitor_mode:
            monitor_mode = next((mode for mode in ("poll", "manual", "heartbeat") if mode in monitor_modes), "manual")
        resolution = {
            "provider": provider,
            "adapter_version": str(adapter.get("adapter_version", "0")),
            "model_id": model_id,
            "reasoning_profile": profile,
            "provider_reasoning_effort": provider_effort,
            "worker_type": (adapter.get("worker_types") or ["agent-thread"])[0],
            "monitor_mode": monitor_mode,
            "capabilities": sorted(set(required_capabilities)),
            "evidence_kinds": sorted(set(required_evidence)),
            "resolved_at": dispatch.get("selected_at") or now,
            "reason": policy.get("reason") or "migrated from legacy model_policy",
        }
        dispatch.update(
            {
                "provider_policy": {"mode": "pinned", "provider": provider},
                "required_capabilities": sorted(set(required_capabilities)),
                "required_evidence_kinds": sorted(set(required_evidence)),
                "model_request": {
                    "quality": model.get("quality", "any"),
                    "reasoning_profile": profile,
                    "latency": "normal",
                    "cost": "balanced",
                },
                "fallback_policy": {
                    "mode": "strict",
                    "allowed_providers": [provider],
                    "allow_model_substitution": False,
                    "allow_manual_monitoring": False,
                },
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
            run["model_id"] = run.pop("selected_model", None) or resolution["model_id"]
            run["reasoning_profile"] = resolution["reasoning_profile"]
            run["provider_reasoning_effort"] = (
                run.pop("reasoning_effort", None) or resolution["provider_reasoning_effort"]
            )
            run["resolution_reason"] = (
                run.pop("model_reason", None) or resolution["reason"]
            )
            run.pop("model_tier", None)
        for lock in task.get("resources", {}).get("locks", []):
            holder = str(lock.get("holder_run_id") or "")
            if holder in run_id_map:
                lock["holder_run_id"] = run_id_map[holder]

    dispatch.setdefault("reason", "migrated dispatch")
    dispatch.setdefault("worker_required", strategy != "direct")
    dispatch.setdefault("heartbeat_required", False)
    dispatch.setdefault("selected_at", now)
    dispatch.setdefault("max_parallel_workers", None if strategy == "direct" else 1)
    dispatch.setdefault("batch", None)
    dispatch.setdefault("heartbeat", None)
    dispatch.setdefault("escalation_triggers", [])
    return task


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


def atomic_write_with_backup(path: Path, rendered: str) -> Path:
    backup = path.with_suffix(path.suffix + ".v1.bak")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate PM dispatch documents to schema v2.")
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
    adapter_schema = load_structured_file(schema_dir / "adapter.schema.json")
    for name, schema in (
        ("task.schema.json", task_schema),
        ("evidence.schema.json", evidence_schema),
        ("adapter.schema.json", adapter_schema),
    ):
        assert_supported_schema(schema, name)
    adapter_catalog, adapter_errors = load_adapters(adapter_dir, adapter_schema)
    if adapter_errors:
        raise MigrationError("invalid adapter catalog: " + "; ".join(adapter_errors))
    now = args.now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    pending: list[tuple[Path, dict[str, Any], str, str, bool]] = []
    for path in collect_paths(args.paths):
        document = load_structured_file(path)
        if "dispatch" in document or "id" in document:
            migrated = migrate_task(document, adapter_catalog, now)
            document_type = "task"
        elif "task_id" in document:
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
        pending.append((path, migrated, rendered, document_type, migrated != document))

    if not args.write:
        for path, _, rendered, _, _ in pending:
            print(f"--- {path}")
            print(rendered, end="")
        return 0

    for path, _, rendered, _, changed in pending:
        if not changed:
            print(f"unchanged {path}")
            continue
        backup = atomic_write_with_backup(path, rendered)
        print(f"migrated {path} (backup: {backup})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

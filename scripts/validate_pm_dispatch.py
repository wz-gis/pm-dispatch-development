#!/usr/bin/env python3
"""Validate PM dispatch task/evidence files and enforce gate policy.

This script intentionally has no required third-party dependencies. If PyYAML is
installed it is used; otherwise a small YAML subset parser handles the templates
produced by this skill.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_RUN_STATUSES = {"queued", "running"}
ACTIVE_LOCK_STATUSES = {"active"}
VERIFIED_STATUSES = {
    "VERIFIED",
    "L0_VERIFIED_MOCK",
    "L1_VERIFIED_MOCK",
    "L2_VERIFIED_MOCK",
    "L3_VERIFIED_MOCK",
    "L4_VERIFIED_MOCK",
}
BLOCKED_STATUSES = {"ENV_BLOCKED", "CONTRACT_BLOCKED", "THREAD_BLOCKED", "PM_BLOCKED"}
EVIDENCE_REQUIRED_STATUSES = VERIFIED_STATUSES | BLOCKED_STATUSES | {
    "READY_FOR_CLOSURE",
    "PARTIAL_VERIFIED",
    "CLOSED",
}
POST_DEPENDENCY_STATUSES = {
    "READY_FOR_IMPL",
    "IN_IMPL",
    "READY_FOR_INTEGRATION",
    "IN_INTEGRATION",
    "READY_FOR_CLOSURE",
    "VERIFIED",
    "CLOSED",
}
TASK_ID_RE = re.compile(r"^(BUG|SPEC|ONBOARD|RELEASE|ENV|CHORE)-[0-9]{3}$")
WORKER_PREFIX_RE = r"(?:(?:BUG|SPEC|ONBOARD|RELEASE|ENV|CHORE)-[0-9]{3}|BATCH-[A-Z0-9]+(?:-[A-Z0-9]+)*)"
WORKER_NAME_RE = re.compile(rf"^{WORKER_PREFIX_RE}-(contract|impl|integration|verify|closure)-w[0-9]{{2}}$")
RUN_ID_RE = re.compile(rf"^run-{WORKER_PREFIX_RE}-(contract|impl|integration|verify|closure)-w[0-9]{{2}}$")
ATTEMPT_ID_RE = re.compile(rf"^attempt-{WORKER_PREFIX_RE}-(contract|impl|integration|verify|closure)-w[0-9]{{2}}-a[0-9]{{2}}$")
GATE_SLUG_BY_GATE = {
    "contract": "contract",
    "implementation": "impl",
    "integration": "integration",
    "verification": "verify",
    "closure": "closure",
}
TYPE_BY_PREFIX = {
    "BUG": "bug",
    "SPEC": "spec",
    "ONBOARD": "onboarding",
    "RELEASE": "release",
    "ENV": "environment",
    "CHORE": "chore",
}
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "blocked", "expired", "cancelled"}
STATE_PHASES = {
    "NEW": {"intake"},
    "TRIAGED": {"triage"},
    "CONTRACT": {"contract"},
    "READY_FOR_IMPL": {"implementation"},
    "IN_IMPL": {"implementation"},
    "READY_FOR_INTEGRATION": {"integration"},
    "IN_INTEGRATION": {"integration"},
    "READY_FOR_CLOSURE": {"closure"},
    "VERIFIED": {"closure"},
    "PARTIAL_VERIFIED": {"verification", "closure"},
    "L0_VERIFIED_MOCK": {"closure"},
    "L1_VERIFIED_MOCK": {"closure"},
    "L2_VERIFIED_MOCK": {"closure"},
    "L3_VERIFIED_MOCK": {"closure"},
    "L4_VERIFIED_MOCK": {"closure"},
    "CLOSED": {"archive"},
}
VERIFICATION_STATUS_BY_TASK_STATUS = {
    "VERIFIED": {"L0_VERIFIED", "L1_VERIFIED", "L2_VERIFIED", "L3_VERIFIED", "L4_VERIFIED"},
    "PARTIAL_VERIFIED": {"PARTIAL"},
    "L0_VERIFIED_MOCK": {"L0_VERIFIED_MOCK"},
    "L1_VERIFIED_MOCK": {"L1_VERIFIED_MOCK"},
    "L2_VERIFIED_MOCK": {"L2_VERIFIED_MOCK"},
    "L3_VERIFIED_MOCK": {"L3_VERIFIED_MOCK"},
    "L4_VERIFIED_MOCK": {"L4_VERIFIED_MOCK"},
}
ARTIFACT_GROUP_KINDS = {
    "api": "api",
    "sql": "sql",
    "browser": "browser",
    "screenshots": "screenshot",
    "logs": "log",
    "ids": "id",
    "upgrade_path": "upgrade_path",
    "release_path": "release_path",
}
BLOCKER_TYPE_BY_STATUS = {
    "ENV_BLOCKED": "environment",
    "CONTRACT_BLOCKED": "contract",
    "THREAD_BLOCKED": "thread",
    "PM_BLOCKED": "pm",
}
OPEN_CLOSURE_STATUSES = {
    "NEW",
    "TRIAGED",
    "CONTRACT",
    "READY_FOR_IMPL",
    "IN_IMPL",
    "READY_FOR_INTEGRATION",
    "IN_INTEGRATION",
} | BLOCKED_STATUSES
QUALITY_RANK = {"fast": 0, "balanced": 1, "frontier": 2}
LATENCY_RANK = {"low": 0, "normal": 1, "high": 2}
COST_RANK = {"economical": 0, "balanced": 1, "premium": 2}
REQUEST_LATENCY_MAX = {"low": 0, "normal": 1, "relaxed": 2}
REQUEST_COST_MAX = {"economical": 0, "balanced": 1, "unbounded": 2}


@dataclass
class LoadedTask:
    path: Path
    task: dict[str, Any]
    evidence: dict[str, Any] | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PM dispatch task.yaml and evidence.yaml.")
    parser.add_argument("task", nargs="?", help="Path to one docs/tasks/<TASK>/task.yaml")
    parser.add_argument("--tasks-dir", help="Validate every */task.yaml in this docs/tasks directory")
    parser.add_argument("--evidence", help="Override evidence.yaml path for single-task validation")
    parser.add_argument("--schema-dir", help="Directory containing task.schema.json and evidence.schema.json")
    parser.add_argument("--adapter-dir", help="Directory containing *.adapter.json provider policies")
    parser.add_argument("--now", help="Override current time, ISO-8601. Defaults to current UTC time")
    args = parser.parse_args()

    if not args.task and not args.tasks_dir:
        parser.error("provide a task.yaml path or --tasks-dir")

    script_dir = Path(__file__).resolve().parent
    schema_dir = Path(args.schema_dir).resolve() if args.schema_dir else script_dir.parent / "references" / "schemas"
    adapter_dir = Path(args.adapter_dir).resolve() if args.adapter_dir else script_dir.parent / "references" / "adapters"
    task_schema = load_structured_file(schema_dir / "task.schema.json")
    evidence_schema = load_structured_file(schema_dir / "evidence.schema.json")
    adapter_schema = load_structured_file(schema_dir / "adapter.schema.json")
    assert_supported_schema(task_schema, "task.schema.json")
    assert_supported_schema(evidence_schema, "evidence.schema.json")
    assert_supported_schema(adapter_schema, "adapter.schema.json")
    adapters, adapter_errors = load_adapters(adapter_dir, adapter_schema)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)

    errors: list[str] = list(adapter_errors)
    warnings: list[str] = []
    loaded: list[LoadedTask] = []

    task_paths = [Path(args.task)] if args.task else sorted(Path(args.tasks_dir).glob("*/task.yaml"))
    for task_path in task_paths:
        task_path = task_path.resolve()
        try:
            task = load_structured_file(task_path)
            task_schema_errors = validate_schema(task, task_schema, f"{task_path}", task_schema)
            errors.extend(task_schema_errors)
        except Exception as exc:
            errors.append(f"{task_path}: cannot load task: {exc}")
            continue
        if task_schema_errors:
            continue

        evidence_path = evidence_file_for(task_path, task, args.evidence if len(task_paths) == 1 else None)
        evidence = None
        if evidence_path.exists():
            try:
                evidence = load_structured_file(evidence_path)
                evidence_schema_errors = validate_schema(
                    evidence, evidence_schema, f"{evidence_path}", evidence_schema
                )
                errors.extend(evidence_schema_errors)
                if evidence_schema_errors:
                    evidence = None
            except Exception as exc:
                errors.append(f"{evidence_path}: cannot load evidence: {exc}")
        elif task.get("status") in EVIDENCE_REQUIRED_STATUSES:
            errors.append(f"{task_path}: status {task.get('status')} requires evidence file {evidence_path}")

        loaded.append(LoadedTask(task_path, task, evidence))

    for item in loaded:
        item_errors, item_warnings = validate_gate_policy(item, now, adapters)
        errors.extend(item_errors)
        warnings.extend(item_warnings)

    graph_errors, graph_warnings = validate_dependency_graph_and_locks(loaded, now)
    errors.extend(graph_errors)
    warnings.extend(graph_warnings)

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PM dispatch validation passed ({len(loaded)} task(s)).")
    return 0


def evidence_file_for(task_path: Path, task: dict[str, Any], override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    configured = task.get("verification", {}).get("evidence_file")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else (task_path.parent / path).resolve()
    return task_path.with_name("evidence.yaml")


def validate_gate_policy(
    item: LoadedTask, now: datetime, adapters: dict[str, dict[str, Any]]
) -> tuple[list[str], list[str]]:
    task = item.task
    evidence = item.evidence
    prefix = str(item.path)
    errors: list[str] = []
    warnings: list[str] = []

    status = task.get("status")
    open_blockers = [b for b in task.get("blockers", []) if b.get("status") == "open"]
    if status in VERIFIED_STATUSES | {"CLOSED"} and open_blockers:
        errors.append(f"{prefix}: verified-like status is blocked by open blockers: {ids(open_blockers)}")

    task_id = task.get("id", "")
    if not TASK_ID_RE.fullmatch(str(task_id)):
        errors.append(f"{prefix}: task id must look like BUG-041 or SPEC-001")
    if item.path.parent.name != str(task_id):
        errors.append(f"{prefix}: task directory name {item.path.parent.name!r} must match task id {task_id!r}")
    task_prefix = str(task_id).split("-", 1)[0]
    expected_type = TYPE_BY_PREFIX.get(task_prefix)
    if expected_type and task.get("type") != expected_type:
        errors.append(f"{prefix}: task id prefix {task_prefix} does not match task type {task.get('type')!r}")
    area_label = "/".join(str(value) for value in task.get("area", []))
    expected_display_name = f"{task_id} {task.get('priority')} {area_label} {task.get('title')}"
    if task.get("display_name") != expected_display_name:
        errors.append(f"{prefix}: display_name must equal {expected_display_name!r}")

    phase = task.get("lifecycle", {}).get("phase")
    allowed_phases = STATE_PHASES.get(str(status))
    if allowed_phases and phase not in allowed_phases:
        errors.append(f"{prefix}: status {status} requires lifecycle.phase in {sorted(allowed_phases)}, got {phase!r}")
    verification_status = task.get("verification", {}).get("status")
    expected_verification = VERIFICATION_STATUS_BY_TASK_STATUS.get(str(status))
    if expected_verification and verification_status not in expected_verification:
        errors.append(
            f"{prefix}: status {status} requires verification.status in {sorted(expected_verification)}, "
            f"got {verification_status!r}"
        )
    closure_status = task.get("closure", {}).get("status")
    if status in OPEN_CLOSURE_STATUSES and closure_status != "open":
        errors.append(f"{prefix}: status {status} requires closure.status=open")
    if status == "PARTIAL_VERIFIED" and closure_status not in {"open", "ready"}:
        errors.append(f"{prefix}: status PARTIAL_VERIFIED requires closure.status=open or ready")
    if status in VERIFIED_STATUSES and closure_status not in {"ready", "closed"}:
        errors.append(f"{prefix}: status {status} requires closure.status=ready or closed")
    if status == "READY_FOR_CLOSURE" and closure_status != "ready":
        errors.append(f"{prefix}: status READY_FOR_CLOSURE requires closure.status=ready")
    if status == "CLOSED":
        closure = task.get("closure", {})
        if phase != "archive" or closure_status != "closed":
            errors.append(f"{prefix}: status CLOSED requires lifecycle.phase=archive and closure.status=closed")
        for field in ("accepted_by", "accepted_at", "closed_at"):
            if not closure.get(field):
                errors.append(f"{prefix}: status CLOSED requires closure.{field}")
        if not str(verification_status).endswith(("_VERIFIED", "_VERIFIED_MOCK")):
            errors.append(f"{prefix}: status CLOSED requires verified-like verification.status")
    if status in BLOCKED_STATUSES:
        if verification_status != "BLOCKED":
            errors.append(f"{prefix}: blocked status {status} requires verification.status=BLOCKED")
        if not open_blockers:
            errors.append(f"{prefix}: blocked status {status} requires an open blocker")
        expected_blocker_type = BLOCKER_TYPE_BY_STATUS.get(str(status))
        if expected_blocker_type and not any(blocker.get("type") == expected_blocker_type for blocker in open_blockers):
            errors.append(f"{prefix}: status {status} requires an open {expected_blocker_type} blocker")

    seen_run_ids: set[str] = set()
    seen_worker_names: set[str] = set()
    for run in task.get("runs", []):
        run_id = str(run.get("run_id") or "")
        worker_name = str(run.get("worker_name") or "")
        worker_id = run.get("worker_id")
        gate = run.get("gate")
        gate_slug = GATE_SLUG_BY_GATE.get(str(gate))

        if run_id in seen_run_ids:
            errors.append(f"{prefix}: duplicate run_id {run_id}")
        seen_run_ids.add(run_id)
        if worker_name:
            if worker_name in seen_worker_names:
                errors.append(f"{prefix}: duplicate worker_name {worker_name}")
            seen_worker_names.add(worker_name)

        if run_id == str(task_id):
            errors.append(f"{prefix}: run_id must not equal task id {task_id}")
        if worker_name == str(task_id):
            errors.append(f"{prefix}: worker_name must not equal task id {task_id}")
        if worker_id in {task_id, worker_name, run_id}:
            errors.append(f"{prefix}: worker_id must be the target identifier, not copied from task/run/worker name")
        if not worker_name:
            errors.append(f"{prefix}: run {run_id or 'unknown'} requires worker_name")
        elif not WORKER_NAME_RE.fullmatch(worker_name):
            errors.append(f"{prefix}: worker_name {worker_name!r} must look like BUG-041-impl-w01 or BATCH-AA-impl-w01")
        elif gate_slug and worker_gate_slug(worker_name) != gate_slug:
            errors.append(f"{prefix}: worker_name {worker_name!r} does not match gate {gate!r}; expected role {gate_slug!r}")

        if run_id and not RUN_ID_RE.fullmatch(run_id):
            errors.append(f"{prefix}: run_id {run_id!r} must look like run-<worker_name>")
        elif worker_name and run_id != f"run-{worker_name}":
            errors.append(f"{prefix}: run_id {run_id!r} must equal run-{worker_name}")

        if run.get("status") in ACTIVE_RUN_STATUSES and not worker_id:
            errors.append(f"{prefix}: active run requires worker_id: {run_id}")
        if worker_name.startswith(f"{task_id}-"):
            role = worker_gate_slug(worker_name)
            worker_number = worker_name.rsplit("-w", 1)[-1]
            expected_label = f"{task.get('display_name')} [{role} w{worker_number}]"
            if run.get("worker_label") != expected_label:
                errors.append(f"{prefix}: worker_label must equal {expected_label!r}")
        elif worker_name.startswith("BATCH-") and task.get("dispatch", {}).get("batch"):
            role = worker_gate_slug(worker_name)
            worker_number = worker_name.rsplit("-w", 1)[-1]
            batch_display_name = task["dispatch"]["batch"].get("display_name")
            expected_label = f"{batch_display_name} [{role} w{worker_number}]"
            if run.get("worker_label") != expected_label:
                errors.append(f"{prefix}: batch worker_label must equal {expected_label!r}")

        seen_attempt_ids: set[str] = set()
        active_attempts: list[dict[str, Any]] = []
        for attempt in run.get("attempts", []):
            attempt_id = str(attempt.get("attempt_id") or "")
            if attempt_id in seen_attempt_ids:
                errors.append(f"{prefix}: duplicate attempt_id {attempt_id}")
            seen_attempt_ids.add(attempt_id)
            if attempt_id == str(task_id) or attempt_id == run_id:
                errors.append(f"{prefix}: attempt_id must not equal task id or run_id")
            if attempt_id and not ATTEMPT_ID_RE.fullmatch(attempt_id):
                errors.append(f"{prefix}: attempt_id {attempt_id!r} must look like attempt-<worker_name>-aNN")
            elif worker_name and not attempt_id.startswith(f"attempt-{worker_name}-a"):
                errors.append(f"{prefix}: attempt_id {attempt_id!r} must be derived from worker_name {worker_name!r}")
            if attempt.get("status") in ACTIVE_RUN_STATUSES:
                active_attempts.append(attempt)
        if run.get("status") in ACTIVE_RUN_STATUSES:
            if len(active_attempts) != 1:
                errors.append(f"{prefix}: active run {run_id} requires exactly one active attempt")
            lease = latest_lease(run)
            if not lease:
                errors.append(f"{prefix}: active run {run.get('run_id')} has no lease")
                continue
            if lease.get("holder") != run_id:
                errors.append(f"{prefix}: active run {run_id} lease holder must equal run_id")
            expires_at = parse_time(lease.get("expires_at"))
            if expires_at <= now:
                errors.append(f"{prefix}: active run {run.get('run_id')} lease expired at {lease.get('expires_at')}")
            acquired_at = parse_time(lease.get("acquired_at"))
            if acquired_at >= expires_at:
                errors.append(f"{prefix}: active run {run_id} lease expires before it was acquired")
        elif active_attempts:
            errors.append(f"{prefix}: terminal run {run_id} cannot contain active attempts")

    active_by_gate: dict[str, list[str]] = {}
    for run in task.get("runs", []):
        if run.get("status") in ACTIVE_RUN_STATUSES and not run.get("allow_parallel", False):
            active_by_gate.setdefault(run.get("gate", "unknown"), []).append(run.get("run_id", "unknown"))
    for gate, run_ids in active_by_gate.items():
        if len(run_ids) > 1:
            errors.append(f"{prefix}: duplicate active non-parallel runs for gate {gate}: {', '.join(run_ids)}")

    dispatch = task.get("dispatch", {})
    strategy = dispatch.get("strategy")
    active_runs = [run for run in task.get("runs", []) if run.get("status") in ACTIVE_RUN_STATUSES]
    if strategy == "direct" and task.get("runs"):
        errors.append(f"{prefix}: dispatch.strategy=direct cannot have worker runs")
    if strategy == "direct" and dispatch.get("worker_required") is not False:
        errors.append(f"{prefix}: dispatch.strategy=direct requires worker_required=false")
    if strategy == "direct" and dispatch.get("heartbeat_required") is not False:
        errors.append(f"{prefix}: dispatch.strategy=direct requires heartbeat_required=false")
    provider_policy = dispatch.get("provider_policy") or {}
    if strategy == "direct" and provider_policy != {"mode": "local", "provider": "local"}:
        errors.append(f"{prefix}: dispatch.strategy=direct requires local provider_policy")
    if strategy == "direct" and dispatch.get("required_capabilities"):
        errors.append(f"{prefix}: dispatch.strategy=direct requires required_capabilities=[]")
    if strategy == "direct" and dispatch.get("required_evidence_kinds"):
        errors.append(f"{prefix}: dispatch.strategy=direct requires required_evidence_kinds=[]")
    if strategy == "direct" and dispatch.get("model_request") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires model_request=null")
    if strategy == "direct" and dispatch.get("fallback_policy") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires fallback_policy=null")
    if strategy == "direct" and dispatch.get("resolution") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires resolution=null")
    if strategy == "direct" and dispatch.get("heartbeat") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires heartbeat=null")
    if strategy == "single-worker" and len(active_runs) > 1:
        errors.append(f"{prefix}: dispatch.strategy=single-worker allows at most one active run")
    if strategy in {"single-worker", "batch-worker", "full-dispatch"} and dispatch.get("worker_required") is not True:
        errors.append(f"{prefix}: dispatch.strategy={strategy} requires worker_required=true")
    if status in {"IN_IMPL", "IN_INTEGRATION"} and strategy != "direct" and not task.get("runs"):
        errors.append(f"{prefix}: dispatch.strategy={strategy} in status {status} requires at least one run")
    max_parallel = dispatch.get("max_parallel_workers")
    if max_parallel is not None:
        if max_parallel < 1:
            errors.append(f"{prefix}: max_parallel_workers must be >= 1")
        elif len(active_runs) > max_parallel:
            errors.append(
                f"{prefix}: active run count {len(active_runs)} exceeds max_parallel_workers={max_parallel}"
            )
    heartbeat_required = dispatch.get("heartbeat_required")
    resolved_monitor = (dispatch.get("resolution") or {}).get("monitor_mode")
    if heartbeat_required and resolved_monitor == "heartbeat" and not dispatch.get("heartbeat"):
        errors.append(f"{prefix}: heartbeat_required=true requires heartbeat metadata")
    if (not heartbeat_required or resolved_monitor not in {None, "heartbeat"}) and dispatch.get("heartbeat"):
        errors.append(f"{prefix}: heartbeat metadata requires heartbeat_required=true")
    heartbeat = dispatch.get("heartbeat")
    if heartbeat and not active_runs and heartbeat.get("status") == "active":
        errors.append(f"{prefix}: heartbeat must be stopped or paused when no active runs remain")
    for run in task.get("runs", []):
        worker_name = str(run.get("worker_name") or "")
        if not worker_name:
            continue
        if strategy == "batch-worker":
            if not worker_name.startswith("BATCH-"):
                errors.append(f"{prefix}: dispatch.strategy=batch-worker requires BATCH-* worker_name, got {worker_name!r}")
        elif strategy in {"single-worker", "full-dispatch"} and not worker_name.startswith(f"{task_id}-"):
            errors.append(f"{prefix}: dispatch.strategy={strategy} requires worker_name to start with task id {task_id!r}, got {worker_name!r}")
    if strategy in {"single-worker", "batch-worker", "full-dispatch"}:
        if not dispatch.get("required_capabilities"):
            errors.append(f"{prefix}: dispatch.strategy={strategy} requires required_capabilities")
        if not dispatch.get("required_evidence_kinds"):
            errors.append(f"{prefix}: dispatch.strategy={strategy} requires required_evidence_kinds")
        for field in ("model_request", "fallback_policy", "resolution"):
            if not dispatch.get(field):
                errors.append(f"{prefix}: dispatch.strategy={strategy} requires dispatch.{field}")
        if all(dispatch.get(field) for field in ("model_request", "fallback_policy", "resolution")):
            validate_adapter_resolution(task, adapters, errors, prefix)

    batch = dispatch.get("batch")
    if strategy == "batch-worker":
        if not batch:
            errors.append(f"{prefix}: batch-worker requires dispatch.batch")
        elif task_id not in batch.get("task_ids", []):
            errors.append(f"{prefix}: dispatch.batch.task_ids must include current task {task_id}")
    elif batch is not None:
        errors.append(f"{prefix}: dispatch.batch is only valid for batch-worker")

    if not evidence:
        return errors, warnings

    if evidence.get("task_id") != task.get("id"):
        errors.append(f"{prefix}: evidence task_id {evidence.get('task_id')} does not match task id {task.get('id')}")

    conclusion = evidence.get("conclusion", {})
    if status == "VERIFIED":
        if conclusion.get("status") != "VERIFIED":
            errors.append(f"{prefix}: task VERIFIED but evidence conclusion is {conclusion.get('status')}")
        if conclusion.get("mock_based"):
            errors.append(f"{prefix}: task VERIFIED cannot use mock_based evidence; use L*_VERIFIED_MOCK or PARTIAL_VERIFIED")

    if str(status).endswith("_VERIFIED_MOCK"):
        if not conclusion.get("mock_based") or not conclusion.get("accepted_fallback"):
            errors.append(f"{prefix}: mock verification requires mock_based=true and accepted_fallback")
        if conclusion.get("status") != status:
            errors.append(f"{prefix}: task {status} requires matching evidence conclusion")
    if status == "PARTIAL_VERIFIED" and conclusion.get("status") != "PARTIAL_VERIFIED":
        errors.append(f"{prefix}: task PARTIAL_VERIFIED requires matching evidence conclusion")
    if status == "PARTIAL_VERIFIED" and not (
        task.get("verification", {}).get("missing") or evidence.get("verification", {}).get("uncovered_items") or open_blockers
    ):
        errors.append(f"{prefix}: PARTIAL_VERIFIED requires a documented missing or uncovered item")
    if status in BLOCKED_STATUSES and conclusion.get("status") != status:
        errors.append(f"{prefix}: task {status} requires matching evidence conclusion")
    if status == "CLOSED" and conclusion.get("status") not in VERIFIED_STATUSES:
        errors.append(f"{prefix}: task CLOSED requires a verified-like evidence conclusion")

    enforce_verification = status in VERIFIED_STATUSES | {"READY_FOR_CLOSURE", "CLOSED"}
    required_levels = task.get("verification", {}).get("required_levels", [])
    levels = evidence.get("verification", {}).get("levels", {})
    artifacts = evidence.get("artifacts", {})
    artifact_index = validate_artifacts(artifacts, errors, prefix)
    if enforce_verification:
        for level in required_levels:
            level_data = levels.get(level, {})
            level_status = level_data.get("status")
            if level_status not in {"pass", "pass_mock"}:
                errors.append(f"{prefix}: required {level} evidence is {level_status or 'missing'}")
            if level_status == "pass_mock" and not conclusion.get("accepted_fallback"):
                errors.append(f"{prefix}: {level} uses mock evidence without accepted_fallback")
            for evidence_ref in level_data.get("evidence_refs", []):
                artifact = artifact_index.get(evidence_ref)
                if not artifact:
                    errors.append(f"{prefix}: {level} evidence_ref {evidence_ref!r} does not match an artifact_id")
                elif level_status in {"pass", "pass_mock"} and artifact.get("result") != "pass":
                    errors.append(
                        f"{prefix}: {level} references non-passing artifact {evidence_ref!r}"
                    )
    surfaces = [s.lower() for s in evidence.get("verification", {}).get("changed_surface", [])]
    needs_l2 = "L2" in required_levels or any(matches_any(s, ["api", "dto", "status", "async", "service"]) for s in surfaces)
    needs_l3 = "L3" in required_levels or any(matches_any(s, ["ui", "page", "button", "tab", "modal", "route", "browser"]) for s in surfaces)
    needs_release = any(matches_any(s, ["sql", "schema", "migration", "startup", "package", "release", "static"]) for s in surfaces)

    if enforce_verification:
        if needs_l2 and not any_passing_artifact(artifacts, ("api", "sql", "commands")):
            errors.append(f"{prefix}: L2/API-like change requires api, sql, or command evidence")
        if needs_l3 and not any_passing_artifact(artifacts, ("browser",)):
            errors.append(f"{prefix}: L3/UI-like change requires browser evidence")
        if needs_release and not any_passing_artifact(artifacts, ("upgrade_path", "release_path")):
            errors.append(f"{prefix}: SQL/release-like change requires upgrade_path or release_path evidence")
        if "L4" in required_levels and not (conclusion.get("real_chain_verified") or conclusion.get("accepted_fallback")):
            errors.append(f"{prefix}: L4 requires real_chain_verified=true or accepted_fallback")

    if conclusion.get("status") in VERIFIED_STATUSES and evidence.get("blockers"):
        unresolved = [b for b in evidence.get("blockers", []) if b.get("status") == "open"]
        if unresolved:
            errors.append(f"{prefix}: evidence conclusion is verified-like but has open blockers: {ids(unresolved)}")
    if evidence.get("verification", {}).get("runtime_shape") == "mock" and conclusion.get("real_chain_verified"):
        errors.append(f"{prefix}: mock runtime_shape cannot set real_chain_verified=true")

    task_runs = {run.get("run_id"): run for run in task.get("runs", [])}
    for evidence_run in evidence.get("runs", []):
        run_id = evidence_run.get("run_id")
        task_run = task_runs.get(run_id)
        if not task_run:
            errors.append(f"{prefix}: evidence run {run_id} is not present in task.runs")
            continue
        attempt_ids = {attempt.get("attempt_id") for attempt in task_run.get("attempts", [])}
        if evidence_run.get("attempt_id") not in attempt_ids:
            errors.append(f"{prefix}: evidence attempt {evidence_run.get('attempt_id')} is not present in task run {run_id}")

    return errors, warnings


def validate_dependency_graph_and_locks(items: list[LoadedTask], now: datetime) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    by_id = {item.task.get("id"): item for item in items}

    graph: dict[str, list[str]] = {str(item.task.get("id")): [] for item in items}
    for item in items:
        task = item.task
        for dep in task.get("dependencies", {}).get("requires", []):
            dep_id = dep.get("task_id")
            required = dep.get("required_status")
            source = dep.get("source")
            if source == "board":
                graph[str(task.get("id"))].append(str(dep_id))
                if dep_id not in by_id:
                    errors.append(f"{item.path}: board dependency {dep_id} is not loaded")
                    continue
                actual = by_id[dep_id].task.get("status")
            elif source == "external":
                actual = dep.get("status")
                if not dep.get("evidence_ref"):
                    errors.append(f"{item.path}: external dependency {dep_id} requires evidence_ref")
            else:
                errors.append(f"{item.path}: dependency {dep_id} requires source=board or external")
                continue
            if task.get("status") in POST_DEPENDENCY_STATUSES and actual != required:
                errors.append(f"{item.path}: dependency {dep_id} is {actual}, requires {required}")

    errors.extend(find_dependency_cycles(graph))

    active_locks: dict[str, list[tuple[LoadedTask, dict[str, Any]]]] = {}
    for item in items:
        active_runs = {
            run.get("run_id"): run
            for run in item.task.get("runs", [])
            if run.get("status") in ACTIVE_RUN_STATUSES
        }
        for lock in item.task.get("resources", {}).get("locks", []):
            if lock.get("status") not in ACTIVE_LOCK_STATUSES:
                continue
            expires = lock.get("lease_expires_at")
            if not expires:
                errors.append(f"{item.path}: active resource lock requires lease_expires_at")
                continue
            if parse_time(expires) <= now:
                errors.append(f"{item.path}: resource lock {lock.get('resource_id')} expired at {expires}")
                continue
            holder_run_id = lock.get("holder_run_id")
            holder_run = active_runs.get(holder_run_id)
            if not holder_run:
                errors.append(
                    f"{item.path}: active resource lock {lock.get('resource_id')} references non-active run {holder_run_id}"
                )
                continue
            run_lease = latest_lease(holder_run)
            if not run_lease or parse_time(expires) > parse_time(run_lease.get("expires_at")):
                errors.append(
                    f"{item.path}: resource lock {lock.get('resource_id')} outlives holder run lease"
                )
                continue
            active_locks.setdefault(lock.get("resource_id", "unknown"), []).append((item, lock))

    for resource_id, locks in active_locks.items():
        exclusive = [pair for pair in locks if pair[1].get("mode") == "exclusive"]
        if exclusive and len(locks) > 1:
            holders = ", ".join(f"{item.task.get('id')}:{lock.get('holder_run_id')}" for item, lock in locks)
            errors.append(f"resource {resource_id}: exclusive lock conflict across active holders: {holders}")
    return errors, warnings


def find_dependency_cycles(graph: dict[str, list[str]]) -> list[str]:
    errors: list[str] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            start = visiting.index(node)
            cycle = visiting[start:] + [node]
            message = f"dependency cycle: {' -> '.join(cycle)}"
            if message not in errors:
                errors.append(message)
            return
        if node in visited:
            return
        visiting.append(node)
        for dependency in graph.get(node, []):
            if dependency in graph:
                visit(dependency)
        visiting.pop()
        visited.add(node)

    for node in graph:
        visit(node)
    return errors


def validate_adapter_resolution(
    task: dict[str, Any], adapters: dict[str, dict[str, Any]], errors: list[str], prefix: str
) -> None:
    dispatch = task.get("dispatch", {})
    provider_policy = dispatch.get("provider_policy") or {}
    request = dispatch.get("model_request") or {}
    fallback = dispatch.get("fallback_policy") or {}
    resolution = dispatch.get("resolution") or {}
    provider = resolution.get("provider")
    adapter = adapters.get(str(provider))
    if not adapter:
        errors.append(f"{prefix}: provider {provider!r} has no registered adapter")
        return

    policy_mode = provider_policy.get("mode")
    pinned_provider = provider_policy.get("provider")
    if policy_mode == "local":
        errors.append(f"{prefix}: worker dispatch cannot use provider_policy.mode=local")
    allowed_providers = fallback.get("allowed_providers") or []
    if policy_mode == "pinned" and pinned_provider != provider:
        compatible_fallback = fallback.get("mode") == "compatible" and provider in allowed_providers
        if not compatible_fallback:
            errors.append(
                f"{prefix}: resolution provider {provider!r} differs from pinned provider {pinned_provider!r}"
            )
    elif policy_mode == "auto" and allowed_providers and provider not in allowed_providers:
        errors.append(f"{prefix}: resolution provider {provider!r} is not allowed by fallback_policy")
    if fallback.get("mode") == "strict" and policy_mode == "auto":
        errors.append(f"{prefix}: strict fallback requires a pinned provider")

    if resolution.get("adapter_version") != adapter.get("adapter_version"):
        errors.append(f"{prefix}: resolution adapter_version differs from provider adapter")
    if resolution.get("worker_type") not in adapter.get("worker_types", []):
        errors.append(f"{prefix}: provider {provider!r} does not support worker_type={resolution.get('worker_type')!r}")

    adapter_capabilities = set(adapter.get("capabilities", []))
    required_capabilities = set(dispatch.get("required_capabilities", []))
    resolved_capabilities = set(resolution.get("capabilities", []))
    effective_required = set(required_capabilities)
    manual_fallback = (
        resolution.get("monitor_mode") == "manual"
        and fallback.get("mode") == "compatible"
        and fallback.get("allow_manual_monitoring")
    )
    if manual_fallback:
        effective_required.discard("heartbeat")
    missing = effective_required - adapter_capabilities
    if missing:
        errors.append(f"{prefix}: provider {provider!r} lacks required capabilities: {', '.join(sorted(missing))}")
    if not effective_required.issubset(resolved_capabilities):
        errors.append(f"{prefix}: resolution capabilities do not cover required_capabilities")
    if not resolved_capabilities.issubset(adapter_capabilities):
        errors.append(f"{prefix}: resolution claims capabilities not declared by provider adapter")
    worker_component = adapter.get("components", {}).get("worker", {})
    if "background-worker" in required_capabilities and not worker_component.get("supports_background"):
        errors.append(f"{prefix}: provider {provider!r} worker component does not support background execution")

    required_evidence = set(dispatch.get("required_evidence_kinds", []))
    resolved_evidence = set(resolution.get("evidence_kinds", []))
    adapter_evidence = set(
        adapter.get("components", {}).get("evidence", {}).get("artifact_kinds", [])
    )
    if not required_evidence.issubset(resolved_evidence):
        errors.append(f"{prefix}: resolution evidence_kinds do not cover required_evidence_kinds")
    if not resolved_evidence.issubset(adapter_evidence):
        errors.append(f"{prefix}: resolution claims evidence kinds not declared by provider adapter")

    model_id = resolution.get("model_id")
    model = next((candidate for candidate in adapter.get("models", []) if candidate.get("id") == model_id), None)
    if not model:
        errors.append(f"{prefix}: provider {provider!r} does not declare model_id={model_id!r}")
        return
    requested_quality = request.get("quality")
    model_quality = QUALITY_RANK.get(model.get("quality"), -1)
    required_quality = QUALITY_RANK.get(requested_quality, -1)
    if requested_quality != "any" and model_quality < required_quality:
        errors.append(
            f"{prefix}: model {model_id!r} quality={model.get('quality')!r} does not satisfy request {requested_quality!r}"
        )
    model_latency = LATENCY_RANK.get(model.get("latency_class"), 99)
    if model_latency > REQUEST_LATENCY_MAX.get(request.get("latency"), -1):
        errors.append(f"{prefix}: model {model_id!r} does not satisfy latency request")
    model_cost = COST_RANK.get(model.get("cost_class"), 99)
    if model_cost > REQUEST_COST_MAX.get(request.get("cost"), -1):
        errors.append(f"{prefix}: model {model_id!r} does not satisfy cost request")
    if fallback.get("mode") == "strict" and not fallback.get("allow_model_substitution"):
        default_model = adapter.get("components", {}).get("model", {}).get("default_model")
        if model_id != default_model:
            errors.append(f"{prefix}: strict model policy requires default_model={default_model!r}")
    profile = request.get("reasoning_profile")
    if resolution.get("reasoning_profile") != profile:
        errors.append(f"{prefix}: resolution reasoning_profile differs from model_request")
    expected_effort = model.get("reasoning_profiles", {}).get(profile)
    if not expected_effort:
        errors.append(f"{prefix}: model {model_id!r} does not map reasoning_profile={profile!r}")
    elif resolution.get("provider_reasoning_effort") != expected_effort:
        errors.append(f"{prefix}: resolution provider_reasoning_effort differs from adapter mapping")

    monitor_modes = set(adapter.get("components", {}).get("monitor", {}).get("modes", []))
    monitor_mode = resolution.get("monitor_mode")
    if monitor_mode not in monitor_modes:
        errors.append(f"{prefix}: provider {provider!r} does not support monitor_mode={monitor_mode!r}")
    if dispatch.get("heartbeat_required") and monitor_mode != "heartbeat":
        manual_allowed = fallback.get("mode") == "compatible" and fallback.get("allow_manual_monitoring")
        if not (manual_allowed and monitor_mode == "manual"):
            errors.append(f"{prefix}: heartbeat monitoring was downgraded without compatible manual fallback")

    for run in task.get("runs", []):
        fields = {
            "provider": "provider",
            "adapter_version": "adapter_version",
            "model_id": "model_id",
            "reasoning_profile": "reasoning_profile",
            "provider_reasoning_effort": "provider_reasoning_effort",
            "worker_type": "worker_type",
        }
        for run_field, resolution_field in fields.items():
            if run.get(run_field) != resolution.get(resolution_field):
                errors.append(
                    f"{prefix}: run {run.get('run_id')} {run_field} differs from dispatch resolution"
                )


def validate_artifacts(
    artifacts: dict[str, Any], errors: list[str], prefix: str
) -> dict[str, dict[str, Any]]:
    seen_ids: set[str] = set()
    artifact_index: dict[str, dict[str, Any]] = {}
    for command in artifacts.get("commands", []):
        artifact_id = command.get("artifact_id") if isinstance(command, dict) else None
        if artifact_id in seen_ids:
            errors.append(f"{prefix}: duplicate artifact_id {artifact_id}")
        seen_ids.add(artifact_id)
        if isinstance(command, dict):
            if artifact_id:
                artifact_index[str(artifact_id)] = command
            if command.get("result") == "pass" and command.get("exit_code") != 0:
                errors.append(f"{prefix}: passing command artifact {artifact_id} requires exit_code=0")
    for group, expected_kind in ARTIFACT_GROUP_KINDS.items():
        for artifact in artifacts.get(group, []):
            if not isinstance(artifact, dict):
                continue
            artifact_id = artifact.get("artifact_id")
            if artifact_id in seen_ids:
                errors.append(f"{prefix}: duplicate artifact_id {artifact_id}")
            seen_ids.add(artifact_id)
            if artifact_id:
                artifact_index[str(artifact_id)] = artifact
            if artifact.get("kind") != expected_kind:
                errors.append(f"{prefix}: artifact {artifact_id} in {group} must use kind={expected_kind}")
            if group == "api" and artifact.get("result") == "pass" and artifact.get("status_code") is None:
                errors.append(f"{prefix}: API artifact {artifact_id} requires status_code")
    return artifact_index


def any_passing_artifact(artifacts: dict[str, Any], groups: tuple[str, ...]) -> bool:
    return any(
        isinstance(artifact, dict) and artifact.get("result") == "pass"
        for group in groups
        for artifact in artifacts.get(group, [])
    )


SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "$id",
    "$ref",
    "$defs",
    "title",
    "type",
    "additionalProperties",
    "required",
    "properties",
    "enum",
    "pattern",
    "format",
    "minLength",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minimum",
}


def assert_supported_schema(schema: dict[str, Any], path: str) -> None:
    unsupported = set(schema) - SUPPORTED_SCHEMA_KEYWORDS
    if unsupported:
        raise ValueError(f"{path}: unsupported schema keywords: {sorted(unsupported)}")
    for name, child in schema.get("properties", {}).items():
        assert_supported_schema(child, f"{path}.properties.{name}")
    for name, child in schema.get("$defs", {}).items():
        assert_supported_schema(child, f"{path}.$defs.{name}")
    if isinstance(schema.get("items"), dict):
        assert_supported_schema(schema["items"], f"{path}.items")


def load_adapters(
    adapter_dir: Path, adapter_schema: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    adapters: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if not adapter_dir.exists():
        return adapters, errors
    for path in sorted(adapter_dir.glob("*.adapter.json")):
        adapter = load_structured_file(path)
        schema_errors = validate_schema(adapter, adapter_schema, str(path), adapter_schema)
        errors.extend(schema_errors)
        if schema_errors:
            continue
        integrity_errors = validate_adapter_integrity(adapter, str(path))
        errors.extend(integrity_errors)
        if integrity_errors:
            continue
        provider = adapter.get("provider")
        if provider:
            if provider in adapters:
                errors.append(f"{path}: duplicate provider adapter {provider!r}")
                continue
            adapters[str(provider)] = adapter
    return adapters, errors


def validate_adapter_integrity(adapter: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    models = adapter.get("models") or []
    model_ids = [str(model.get("id")) for model in models if model.get("id")]
    duplicate_ids = sorted({model_id for model_id in model_ids if model_ids.count(model_id) > 1})
    for model_id in duplicate_ids:
        errors.append(f"{prefix}: duplicate model id {model_id!r}")

    model_component = adapter.get("components", {}).get("model", {})
    default_model = model_component.get("default_model")
    if default_model not in model_ids:
        errors.append(f"{prefix}: default_model {default_model!r} is not declared in models")
    for fallback_model in model_component.get("fallback_models", []):
        if fallback_model not in model_ids:
            errors.append(f"{prefix}: fallback model {fallback_model!r} is not declared in models")

    for model in models:
        if not model.get("reasoning_profiles"):
            errors.append(f"{prefix}: model {model.get('id')!r} requires at least one reasoning profile")

    worker = adapter.get("components", {}).get("worker", {})
    create = worker.get("create") or {}
    if isinstance(create, dict) and not create.get("worker_id_path"):
        errors.append(f"{prefix}: worker create operation requires worker_id_path")
    for operation_name in ("create", "inspect", "cancel"):
        operation = worker.get(operation_name) or {}
        if not isinstance(operation, dict):
            continue
        for path_field in ("worker_id_path", "status_path"):
            value = operation.get(path_field)
            if value is not None and not str(value).startswith("$."):
                errors.append(
                    f"{prefix}: worker {operation_name}.{path_field} must use a $. path"
                )
    return errors


def latest_lease(run: dict[str, Any]) -> dict[str, Any] | None:
    attempts = run.get("attempts") or []
    for attempt in reversed(attempts):
        lease = attempt.get("lease")
        if lease:
            return lease
    return None


def matches_any(value: str, needles: list[str]) -> bool:
    return any(needle in value for needle in needles)


def worker_gate_slug(worker_name: str) -> str | None:
    match = re.search(r"-(contract|impl|integration|verify|closure)-w[0-9]{2}$", worker_name)
    return match.group(1) if match else None


def ids(items: list[dict[str, Any]], key: str = "id") -> str:
    return ", ".join(str(item.get(key, "unknown")) for item in items)


def load_structured_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json" or text.lstrip().startswith(("{", "[")):
        return json.loads(text)
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return parse_yaml_subset(text)


def parse_yaml_subset(text: str) -> Any:
    raw_lines = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "\t" in line:
            raise ValueError(f"tabs are not supported in YAML fallback parser at line {lineno}")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("|") or stripped.endswith(">"):
            raise ValueError("block scalars require PyYAML; install PyYAML or use quoted strings")
        raw_lines.append((len(line) - len(line.lstrip(" ")), stripped, lineno))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(raw_lines):
            return {}, index
        if raw_lines[index][0] < indent:
            return {}, index
        is_list = raw_lines[index][1].startswith("- ")
        return parse_list(index, indent) if is_list else parse_dict(index, indent)

    def parse_dict(index: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while index < len(raw_lines):
            current_indent, stripped, lineno = raw_lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"unexpected indentation at line {lineno}")
            if stripped.startswith("- "):
                break
            key, value = split_key_value(stripped, lineno)
            index += 1
            if value == "":
                if index < len(raw_lines) and raw_lines[index][0] > current_indent:
                    child, index = parse_block(index, raw_lines[index][0])
                    result[key] = child
                else:
                    result[key] = None
            else:
                result[key] = parse_scalar(value)
        return result, index

    def parse_list(index: int, indent: int) -> tuple[list[Any], int]:
        result: list[Any] = []
        while index < len(raw_lines):
            current_indent, stripped, lineno = raw_lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"unexpected indentation at line {lineno}")
            if not stripped.startswith("- "):
                break
            item = stripped[2:].strip()
            index += 1
            if not item:
                if index < len(raw_lines) and raw_lines[index][0] > current_indent:
                    child, index = parse_block(index, raw_lines[index][0])
                    result.append(child)
                else:
                    result.append(None)
            elif ":" in item and not item.startswith(("'", '"')):
                key, value = split_key_value(item, lineno)
                obj: dict[str, Any] = {key: parse_scalar(value) if value else None}
                if index < len(raw_lines) and raw_lines[index][0] > current_indent:
                    child, index = parse_block(index, raw_lines[index][0])
                    if isinstance(child, dict):
                        obj.update(child)
                    else:
                        obj[key] = child
                result.append(obj)
            else:
                result.append(parse_scalar(item))
        return result, index

    parsed, final_index = parse_block(0, raw_lines[0][0] if raw_lines else 0)
    if final_index != len(raw_lines):
        raise ValueError("could not parse complete YAML document")
    return parsed


def split_key_value(text: str, lineno: int) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"expected key: value at line {lineno}")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"empty key at line {lineno}")
    return key, value.strip()


def parse_scalar(value: str) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(part.strip()) for part in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def validate_schema(value: Any, schema: dict[str, Any], path: str, root: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = resolve_ref(schema, root)
    expected = schema.get("type")
    if expected is not None and not type_matches(value, expected):
        errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
        return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']}, got {value!r}")
    if "pattern" in schema and isinstance(value, str) and not re.fullmatch(schema["pattern"], value):
        errors.append(f"{path}: value {value!r} does not match pattern {schema['pattern']}")
    if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
        errors.append(f"{path}: string is shorter than minLength={schema['minLength']}")
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        errors.append(f"{path}: value must be >= {schema['minimum']}")
    if schema.get("format") == "date-time" and isinstance(value, str):
        try:
            parse_time(value)
        except (TypeError, ValueError):
            errors.append(f"{path}: invalid date-time {value!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required key {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}: additional property is not allowed")
        for key, child in value.items():
            if key in properties:
                errors.extend(validate_schema(child, resolve_ref(properties[key], root), f"{path}.{key}", root))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: expected at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: expected at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            serialized = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(serialized) != len(set(serialized)):
                errors.append(f"{path}: array items must be unique")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(validate_schema(item, resolve_ref(item_schema, root), f"{path}[{index}]", root))

    return errors


def resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported schema ref {ref}")
    target: Any = root
    for part in ref[2:].split("/"):
        target = target[part]
    return target


def type_matches(value: Any, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(type_matches(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def parse_time(value: Any) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text = text + "T00:00:00+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate PM dispatch task/evidence files and enforce gate policy.

This script intentionally has no required third-party dependencies. If PyYAML is
installed it is used; otherwise a small YAML subset parser handles the templates
produced by this skill.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wait_policy import (  # noqa: E402
    CODEX_WAIT_MAX_CALLS_PER_RUN,
    CODEX_WAIT_MAX_TIMEOUT_MS,
    CODEX_WAIT_POLICY_NAME,
    codex_wait_policy_applies,
)
from monitor_policy import (  # noqa: E402
    CODEX_INSPECTION_POLICY_ADAPTER_VERSION,
    INSPECTION_MAX_CALLS_PER_CYCLE,
    INSPECTION_MIN_INTERVAL_SECONDS,
    INSPECTION_POLICY_NAME,
    PROVISIONING_MAX_TTL_SECONDS,
    inspection_policy_applies,
    pending_inspection_authorizations,
)


ACTIVE_RUN_STATUSES = {"provisioning", "queued", "running"}
EXECUTING_RUN_STATUSES = {"queued", "running"}
ACTIVE_LOCK_STATUSES = {"active"}
HEARTBEAT_PROMPT_MAX_CHARS = 240
COORDINATOR_HEARTBEAT_INTERVAL_MINUTES = 10
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
@dataclass
class LoadedTask:
    path: Path
    task: dict[str, Any]
    evidence: dict[str, Any] | None
    runtime_path: Path | None = None
    runtime: dict[str, Any] | None = None
    runtime_events: list[dict[str, Any]] = field(default_factory=list)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PM dispatch task.yaml and evidence.yaml.")
    parser.add_argument("task", nargs="?", help="Path to one docs/tasks/<TASK>/task.yaml")
    parser.add_argument("--tasks-dir", help="Validate every */task.yaml in this docs/tasks directory")
    parser.add_argument("--evidence", help="Override evidence.yaml path for single-task validation")
    parser.add_argument("--runtime", help="Override runtime.yaml path for single-task validation")
    parser.add_argument("--schema-dir", help="Directory containing task.schema.json and evidence.schema.json")
    parser.add_argument("--adapter-dir", help="Directory containing *.adapter.json provider policies")
    parser.add_argument(
        "--automation-dir",
        help="Optional Codex automations directory used to verify Heartbeat schedule/status drift",
    )
    parser.add_argument(
        "--codex-session-dir",
        help="Optional Codex sessions directory used to audit native wait_threads calls",
    )
    parser.add_argument("--now", help="Override current time, ISO-8601. Defaults to current UTC time")
    args = parser.parse_args()

    if not args.task and not args.tasks_dir:
        parser.error("provide a task.yaml path or --tasks-dir")

    script_dir = Path(__file__).resolve().parent
    schema_dir = Path(args.schema_dir).resolve() if args.schema_dir else script_dir.parent / "references" / "schemas"
    adapter_dir = Path(args.adapter_dir).resolve() if args.adapter_dir else script_dir.parent / "references" / "adapters"
    automation_dir = Path(args.automation_dir).resolve() if args.automation_dir else None
    codex_session_dir = (
        Path(args.codex_session_dir).resolve() if args.codex_session_dir else None
    )
    task_schema = load_structured_file(schema_dir / "task.schema.json")
    evidence_schema = load_structured_file(schema_dir / "evidence.schema.json")
    runtime_schema = load_structured_file(schema_dir / "runtime.schema.json")
    runtime_event_schema = load_structured_file(schema_dir / "runtime-event.schema.json")
    adapter_schema = load_structured_file(schema_dir / "adapter.schema.json")
    assert_supported_schema(task_schema, "task.schema.json")
    assert_supported_schema(evidence_schema, "evidence.schema.json")
    assert_supported_schema(runtime_schema, "runtime.schema.json")
    assert_supported_schema(runtime_event_schema, "runtime-event.schema.json")
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

        runtime_path = None
        runtime = None
        runtime_events: list[dict[str, Any]] = []
        layout_errors: list[str] = []
        if task.get("schema_version") == "4":
            runtime_path = runtime_file_for(
                task_path,
                task,
                args.runtime if len(task_paths) == 1 else None,
            )
            if runtime_path is None:
                layout_errors.append(f"{task_path}: Task v4 requires runtime_file")
            elif runtime_path.exists():
                try:
                    runtime = load_structured_file(runtime_path)
                    runtime_errors = validate_schema(
                        runtime, runtime_schema, str(runtime_path), runtime_schema
                    )
                    errors.extend(runtime_errors)
                    if runtime_errors:
                        runtime = None
                    else:
                        runtime_events, event_errors = load_runtime_event_log(
                            runtime_path, runtime, runtime_event_schema
                        )
                        errors.extend(event_errors)
                except Exception as exc:
                    errors.append(f"{runtime_path}: cannot load runtime: {exc}")
            else:
                layout_errors.append(f"{task_path}: Task v4 requires runtime file {runtime_path}")
        layout_errors.extend(validate_task_runtime_layout(task, runtime, str(task_path)))
        errors.extend(layout_errors)
        effective_task = compose_task_runtime(task, runtime)

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

        loaded.append(
            LoadedTask(
                task_path,
                effective_task,
                evidence,
                runtime_path,
                runtime,
                runtime_events,
            )
        )

    for item in loaded:
        item_errors, item_warnings = validate_gate_policy(
            item, now, adapters, automation_dir, codex_session_dir
        )
        errors.extend(item_errors)
        warnings.extend(item_warnings)

    errors.extend(validate_project_coordinators(loaded))
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


def runtime_file_for(
    task_path: Path, task: dict[str, Any], override: str | None
) -> Path | None:
    if override:
        return Path(override).resolve()
    configured = task.get("runtime_file")
    if not configured:
        return None
    path = Path(str(configured))
    return path if path.is_absolute() else (task_path.parent / path).resolve()


def validate_task_runtime_layout(
    task: dict[str, Any], runtime: dict[str, Any] | None, prefix: str
) -> list[str]:
    errors: list[str] = []
    version = task.get("schema_version")
    dispatch = task.get("dispatch") or {}
    runtime_dispatch_fields = {"selected_at", "resolution", "heartbeat"}
    if version == "3":
        if task.get("runtime_file"):
            errors.append(f"{prefix}: Task v3 cannot reference a Runtime sidecar")
        for field in ("resources", "runs"):
            if field not in task:
                errors.append(f"{prefix}: legacy Task v3 requires embedded {field}")
        for field in sorted(runtime_dispatch_fields):
            if field not in dispatch:
                errors.append(f"{prefix}: legacy Task v3 requires dispatch.{field}")
        return errors
    if version != "4":
        return errors

    if not task.get("runtime_file"):
        errors.append(f"{prefix}: Task v4 requires runtime_file")
    for field in ("resources", "runs"):
        if field in task:
            errors.append(f"{prefix}: Task v4 keeps {field} in Runtime, not task.yaml")
    for field in sorted(runtime_dispatch_fields):
        if field in dispatch:
            errors.append(
                f"{prefix}: Task v4 keeps dispatch.{field} in Runtime, not task.yaml"
            )
    if runtime:
        if runtime.get("task_id") != task.get("id"):
            errors.append(
                f"{prefix}: Runtime task_id {runtime.get('task_id')!r} "
                f"does not match {task.get('id')!r}"
            )
        if runtime.get("task_schema_version") != "4":
            errors.append(f"{prefix}: Runtime must bind task_schema_version=4")
    return errors


def compose_task_runtime(
    task: dict[str, Any], runtime: dict[str, Any] | None
) -> dict[str, Any]:
    if task.get("schema_version") != "4":
        return task
    effective = copy.deepcopy(task)
    effective_dispatch = effective.setdefault("dispatch", {})
    effective_dispatch["selected_at"] = runtime.get("selected_at") if runtime else None
    effective_dispatch["resolution"] = runtime.get("resolution") if runtime else None
    effective_dispatch["heartbeat"] = runtime.get("heartbeat") if runtime else None
    effective["resources"] = copy.deepcopy(
        runtime.get("resources") if runtime else {"locks": []}
    )
    effective["runs"] = copy.deepcopy(runtime.get("runs") if runtime else [])
    return effective


def load_runtime_event_log(
    runtime_path: Path,
    runtime: dict[str, Any],
    event_schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    configured = runtime.get("event_log_file")
    if not configured:
        return [], [f"{runtime_path}: Runtime requires event_log_file"]
    event_path = Path(str(configured))
    if not event_path.is_absolute():
        event_path = (runtime_path.parent / event_path).resolve()
    if not event_path.exists():
        return [], [f"{runtime_path}: event log does not exist: {event_path}"]

    errors: list[str] = []
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    previous_time: datetime | None = None
    for lineno, raw_line in enumerate(event_path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            errors.append(f"{event_path}:{lineno}: invalid JSON event: {exc}")
            continue
        schema_errors = validate_schema(
            event, event_schema, f"{event_path}:{lineno}", event_schema
        )
        errors.extend(schema_errors)
        if not schema_errors:
            events.append(event)
        event_id = event.get("event_id")
        if event_id in seen_ids:
            errors.append(f"{event_path}:{lineno}: duplicate event_id {event_id!r}")
        seen_ids.add(event_id)
        if event.get("task_id") != runtime.get("task_id"):
            errors.append(
                f"{event_path}:{lineno}: task_id does not match Runtime task_id"
            )
        try:
            occurred_at = parse_time(event.get("occurred_at"))
        except ValueError:
            continue
        if previous_time and occurred_at < previous_time:
            errors.append(f"{event_path}:{lineno}: events must be time ordered")
        previous_time = occurred_at
    return events, errors


def validate_runtime_event_log(
    runtime_path: Path,
    runtime: dict[str, Any],
    event_schema: dict[str, Any],
) -> list[str]:
    return load_runtime_event_log(runtime_path, runtime, event_schema)[1]


def validate_recovery_state(item: LoadedTask) -> list[str]:
    from manage_recovery_ledger import default_path, execution_error, validate_ledger

    path = default_path(item.path)
    if not path.is_file():
        return []  # Legacy records remain readable; preflight creates the canonical ledger.
    try:
        ledger = load_structured_file(path)
        errors = validate_ledger(ledger, path, Path(__file__).resolve().parent.parent / "references" / "schemas")
        if ledger.get("task_id") != item.task.get("id"):
            errors.append(f"{path}: Recovery Ledger task_id does not match Task")
        if errors:
            return errors
        for run in item.task.get("runs", []):
            if run.get("status") not in ACTIVE_RUN_STATUSES:
                continue
            entry = next((gate for gate in ledger["gates"] if gate["gate"] == run.get("gate")), {})
            pending = next((row["attempt_key"] for row in entry.get("attempts", []) if row["result"] == "pending"), None)
            error = execution_error(ledger, run.get("gate"), pending)
            if error:
                errors.append(f"{path}: active Run {run.get('run_id')}: {error}")
        return errors
    except (OSError, ValueError) as exc:
        return [f"{path}: invalid Recovery Ledger: {exc}"]


def validate_gate_policy(
    item: LoadedTask,
    now: datetime,
    adapters: dict[str, dict[str, Any]],
    automation_dir: Path | None = None,
    codex_session_dir: Path | None = None,
) -> tuple[list[str], list[str]]:
    task = item.task
    evidence = item.evidence
    prefix = str(item.path)
    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(validate_recovery_state(item))
    for run in task.get("runs", []):
        observation = run.get("observation") or {}
        if not observation:
            continue
        if observation.get("provider_status") in {"idle", "interrupted"} and run.get("status") == "running":
            errors.append(f"{prefix}: idle/interrupted Worker must be reconciled, not left running")
        attention = observation.get("state") == "attention"
        if attention != bool(observation.get("attention_at") and observation.get("reason")):
            errors.append(f"{prefix}: observation attention state requires a reason and timestamp")
        if bool(observation.get("command_id")) != bool(observation.get("command_deadline")):
            errors.append(f"{prefix}: observed command requires both ID and fixed deadline")

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
        hard_blockers = [blocker for blocker in open_blockers if blocker.get("hard") is True]
        if open_blockers and not hard_blockers:
            errors.append(f"{prefix}: blocked status {status} requires an open hard blocker")
        for blocker in hard_blockers:
            cause = blocker.get("cause")
            attempts = int(blocker.get("recovery_attempts") or 0)
            if cause in {"external-unavailable", "recovery-exhausted"} and attempts < 2:
                errors.append(
                    f"{prefix}: hard blocker {blocker.get('id')} with cause={cause} "
                    "requires at least two materially different recovery attempts"
                )
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

        run_status = run.get("status")
        if run_status in EXECUTING_RUN_STATUSES and not worker_id:
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
        provisioning = run.get("provisioning")
        if run_status == "provisioning":
            if worker_id:
                errors.append(f"{prefix}: provisioning run {run_id} cannot have worker_id")
            if len(active_attempts) != 1 or any(
                attempt.get("status") != "provisioning" for attempt in active_attempts
            ):
                errors.append(
                    f"{prefix}: provisioning run {run_id} requires exactly one provisioning attempt"
                )
            if any(attempt.get("lease") is not None for attempt in active_attempts):
                errors.append(f"{prefix}: provisioning run {run_id} cannot acquire a Lease")
            if not isinstance(provisioning, dict) or provisioning.get("status") != "pending":
                errors.append(
                    f"{prefix}: provisioning run {run_id} requires provisioning.status=pending"
                )
            else:
                started = parse_time(provisioning.get("started_at"))
                deadline = parse_time(provisioning.get("deadline_at"))
                if started >= deadline:
                    errors.append(
                        f"{prefix}: provisioning deadline must follow its start for {run_id}"
                    )
                elif (deadline - started).total_seconds() > PROVISIONING_MAX_TTL_SECONDS:
                    errors.append(
                        f"{prefix}: provisioning run {run_id} exceeds the "
                        f"{PROVISIONING_MAX_TTL_SECONDS}-second deadline limit"
                    )
                if deadline <= now:
                    errors.append(
                        f"{prefix}: provisioning run {run_id} expired at "
                        f"{provisioning.get('deadline_at')}; roll it back"
                    )
                if provisioning.get("finished_at") is not None:
                    errors.append(
                        f"{prefix}: pending provisioning {run_id} cannot have finished_at"
                    )
        elif run_status in EXECUTING_RUN_STATUSES:
            if len(active_attempts) != 1:
                errors.append(f"{prefix}: active run {run_id} requires exactly one active attempt")
            if isinstance(provisioning, dict) and provisioning.get("status") == "pending":
                errors.append(
                    f"{prefix}: active run {run_id} cannot retain pending provisioning"
                )
            lease = latest_lease(run)
            if not lease:
                errors.append(f"{prefix}: active run {run.get('run_id')} has no lease")
                continue
            if lease.get("holder") != run_id:
                errors.append(f"{prefix}: active run {run_id} lease holder must equal run_id")
            expires_at = parse_time(lease.get("expires_at"))
            liveness_state = lease.get("liveness_state")
            monitor_gap_started_at = lease.get("monitor_gap_started_at")
            if expires_at <= now and liveness_state != "unknown":
                errors.append(f"{prefix}: active run {run.get('run_id')} lease expired at {lease.get('expires_at')}")
            if liveness_state == "unknown" and not monitor_gap_started_at:
                errors.append(
                    f"{prefix}: active run {run.get('run_id')} with unknown liveness "
                    "requires monitor_gap_started_at"
                )
            if liveness_state == "live" and monitor_gap_started_at is not None:
                errors.append(
                    f"{prefix}: active run {run.get('run_id')} with live liveness "
                    "must clear monitor_gap_started_at"
                )
            acquired_at = parse_time(lease.get("acquired_at"))
            if acquired_at >= expires_at:
                errors.append(f"{prefix}: active run {run_id} lease expires before it was acquired")
        elif active_attempts:
            errors.append(f"{prefix}: terminal run {run_id} cannot contain active attempts")
        if run_status in TERMINAL_RUN_STATUSES and isinstance(provisioning, dict):
            if provisioning.get("status") == "pending":
                errors.append(
                    f"{prefix}: terminal run {run_id} cannot retain pending provisioning"
                )

    validate_codex_wait_policy(item, errors, warnings, codex_session_dir)
    validate_codex_inspection_policy(item, errors, warnings, codex_session_dir)

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
    if strategy == "direct" and dispatch.get("reasoning_profile") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires reasoning_profile=null")
    if strategy == "direct" and dispatch.get("fallback_policy") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires fallback_policy=null")
    if strategy == "direct" and dispatch.get("resolution") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires resolution=null")
    if strategy == "direct" and dispatch.get("design_freeze") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires design_freeze=null")
    if strategy == "direct" and dispatch.get("heartbeat") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires heartbeat=null")
    if strategy == "direct" and dispatch.get("worker_reuse") is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires worker_reuse=null")
    delegation = dispatch.get("delegation")
    if strategy == "direct" and delegation is not None:
        errors.append(f"{prefix}: dispatch.strategy=direct requires delegation=null or omitted")
    if delegation is not None:
        if strategy != "single-worker":
            errors.append(
                f"{prefix}: delegated subagent execution requires dispatch.strategy=single-worker"
            )
        if provider_policy != {"mode": "pinned", "provider": "codex"}:
            errors.append(
                f"{prefix}: delegated subagent execution requires a pinned visible Codex Worker"
            )
        if dispatch.get("max_parallel_workers") != 1:
            errors.append(
                f"{prefix}: delegated subagent execution requires max_parallel_workers=1"
            )
        if dispatch.get("heartbeat_required") is not True:
            errors.append(
                f"{prefix}: delegated subagent execution requires coordinator heartbeat monitoring"
            )
        missing_wrapper_capabilities = {
            "background-worker",
            "code-edit",
            "git",
            "heartbeat",
            "shell",
        } - set(dispatch.get("required_capabilities") or [])
        if missing_wrapper_capabilities:
            errors.append(
                f"{prefix}: delegated subagent wrapper lacks required capabilities: "
                + ", ".join(sorted(missing_wrapper_capabilities))
            )
    if strategy == "single-worker" and len(active_runs) > 1:
        errors.append(f"{prefix}: dispatch.strategy=single-worker allows at most one active run")
    if strategy == "single-worker":
        reuse = dispatch.get("worker_reuse") or {}
        if reuse.get("mode") != "sticky" or reuse.get("reuse_across_gates") is not True:
            errors.append(
                f"{prefix}: dispatch.strategy=single-worker requires sticky reuse across gates"
            )
        allowed_replacements = set(reuse.get("replacement_triggers") or [])
        previous_worker_id: str | None = None
        for run in task.get("runs", []):
            worker_id = str(run.get("worker_id") or "")
            if not worker_id:
                continue
            replacement_reason = run.get("worker_replacement_reason")
            if previous_worker_id and worker_id != previous_worker_id:
                if replacement_reason == "legacy-history" and run.get("status") in TERMINAL_RUN_STATUSES:
                    pass
                elif replacement_reason not in allowed_replacements:
                    errors.append(
                        f"{prefix}: single-worker changed Worker from {previous_worker_id} "
                        f"to {worker_id} without an allowed worker_replacement_reason"
                    )
            elif replacement_reason is not None:
                errors.append(
                    f"{prefix}: single-worker run {run.get('run_id')} declares "
                    "worker_replacement_reason without changing Worker"
                )
            previous_worker_id = worker_id
    if strategy in {"single-worker", "batch-worker", "full-dispatch"} and dispatch.get("worker_required") is not True:
        errors.append(f"{prefix}: dispatch.strategy={strategy} requires worker_required=true")
    if strategy in {"single-worker", "batch-worker", "full-dispatch"}:
        if not dispatch.get("worker_reuse"):
            errors.append(f"{prefix}: dispatch.strategy={strategy} requires dispatch.worker_reuse")
        freeze = dispatch.get("design_freeze") or {}
        if freeze.get("status") != "frozen":
            errors.append(f"{prefix}: dispatch.strategy={strategy} requires a frozen design before dispatch")
        elif not freeze.get("frozen_at") or not freeze.get("fingerprint"):
            errors.append(f"{prefix}: frozen design requires frozen_at and fingerprint")
        elif freeze.get("fingerprint") != design_freeze_fingerprint(freeze):
            errors.append(f"{prefix}: design_freeze fingerprint does not match frozen constraints")
        active_fingerprint = freeze.get("fingerprint")
        for run in active_runs:
            if run.get("design_fingerprint") != active_fingerprint:
                errors.append(
                    f"{prefix}: active run {run.get('run_id')} design_fingerprint differs "
                    "from the protected dispatch.design_freeze contract; a new Attempt is required"
                )
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
    resolution = dispatch.get("resolution") or {}
    resolved_monitor = resolution.get("monitor_mode")
    codex_visible_worker = (
        strategy in {"single-worker", "batch-worker", "full-dispatch"}
        and resolution.get("provider") == "codex"
        and resolution.get("worker_type") == "codex-thread"
    )
    if codex_visible_worker:
        if heartbeat_required is not True:
            errors.append(
                f"{prefix}: visible Codex Worker requires heartbeat_required=true; "
                "create_thread has no verified parent callback"
            )
        if resolved_monitor != "heartbeat":
            errors.append(
                f"{prefix}: visible Codex Worker requires monitor_mode=heartbeat"
            )
        heartbeat_state = dispatch.get("heartbeat") or {}
        if active_runs and heartbeat_state.get("status") != "active":
            errors.append(
                f"{prefix}: active visible Codex Worker requires an active coordinator Heartbeat"
            )
    if resolved_monitor == "event-lease":
        for run in active_runs:
            if run.get("status") == "provisioning":
                continue
            lease = latest_lease(run) or {}
            heartbeat_at = lease.get("heartbeat_at")
            if not heartbeat_at:
                errors.append(
                    f"{prefix}: event-lease run {run.get('run_id')} requires lease.heartbeat_at"
                )
                continue
            acquired_at = parse_time(lease.get("acquired_at"))
            progress_at = parse_time(heartbeat_at)
            expires_at = parse_time(lease.get("expires_at"))
            if progress_at < acquired_at or progress_at > expires_at:
                errors.append(
                    f"{prefix}: event-lease run {run.get('run_id')} heartbeat_at must be within its Lease"
                )
            last_progress_at = lease.get("last_progress_at")
            if not last_progress_at or not lease.get("last_progress_summary"):
                errors.append(
                    f"{prefix}: event-lease run {run.get('run_id')} requires a persisted progress checkpoint"
                )
            else:
                checkpoint_at = parse_time(last_progress_at)
                if checkpoint_at < acquired_at or checkpoint_at > expires_at:
                    errors.append(
                        f"{prefix}: event-lease run {run.get('run_id')} last_progress_at must be within its Lease"
                    )
    if heartbeat_required and resolved_monitor == "heartbeat" and not dispatch.get("heartbeat"):
        errors.append(f"{prefix}: heartbeat_required=true requires heartbeat metadata")
    if (not heartbeat_required or resolved_monitor not in {None, "heartbeat"}) and dispatch.get("heartbeat"):
        errors.append(f"{prefix}: heartbeat metadata requires heartbeat_required=true")
    heartbeat = dispatch.get("heartbeat")
    if heartbeat:
        heartbeat_status = heartbeat.get("status")
        target_run_id = heartbeat.get("target_run_id")
        runs_by_id = {run.get("run_id"): run for run in task.get("runs", [])}
        target_run = runs_by_id.get(target_run_id)
        if heartbeat.get("scan_scope") != "incremental":
            errors.append(f"{prefix}: heartbeat must use scan_scope=incremental")
        if heartbeat.get("lightweight") is not True:
            errors.append(f"{prefix}: incremental heartbeat inspection requires lightweight=true")
        if set(heartbeat.get("read_set") or []) != {
            "worker-status",
            "lease",
            "latest-milestone",
        }:
            errors.append(
                f"{prefix}: incremental heartbeat read_set must contain only Worker status, "
                "Lease, and latest milestone"
            )
        if set(heartbeat.get("full_scan_triggers") or []) != {
            "milestone",
            "terminal",
            "safety-boundary-change",
            "design-freeze-change",
        }:
            errors.append(f"{prefix}: heartbeat full_scan_triggers do not match the protected contract")
        if heartbeat.get("context_policy") != "coordinator":
            errors.append(f"{prefix}: heartbeat must run in the dispatch coordinator thread")
        if heartbeat.get("interval_minutes") != COORDINATOR_HEARTBEAT_INTERVAL_MINUTES:
            errors.append(
                f"{prefix}: incremental heartbeat inspection interval must equal "
                f"{COORDINATOR_HEARTBEAT_INTERVAL_MINUTES} minutes"
            )
        if not target_run:
            errors.append(f"{prefix}: heartbeat.target_run_id must reference a Run in this task")
        elif heartbeat_status == "active" and target_run.get("status") not in ACTIVE_RUN_STATUSES:
            errors.append(f"{prefix}: active heartbeat must target an active Run")
        worker_ids = {str(run.get("worker_id")) for run in task.get("runs", []) if run.get("worker_id")}
        coordinator_thread_id = str(heartbeat.get("coordinator_thread_id") or "")
        if not coordinator_thread_id:
            errors.append(f"{prefix}: heartbeat requires the PM coordinator_thread_id")
        resolution = dispatch.get("resolution") or {}
        if (
            resolution.get("provider") == "codex"
            and int(str(resolution.get("adapter_version") or "0")) >= 13
            and not isinstance(heartbeat.get("coordinator_epoch"), int)
        ):
            errors.append(f"{prefix}: Codex v13+ heartbeat requires coordinator_epoch")
        if coordinator_thread_id in worker_ids:
            errors.append(
                f"{prefix}: heartbeat coordinator_thread_id must differ from every Worker thread"
            )
        if (
            active_runs
            and heartbeat_required
            and resolved_monitor == "heartbeat"
            and heartbeat_status != "active"
        ):
            errors.append(f"{prefix}: active runs require heartbeat.status=active")
        if not active_runs and heartbeat_status == "active":
            errors.append(f"{prefix}: heartbeat must be stopped or paused when no active runs remain")
        if automation_dir and (dispatch.get("resolution") or {}).get("provider") == "codex":
            validate_codex_heartbeat_automation(
                heartbeat,
                automation_dir,
                errors,
                prefix,
            )
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
        for field in ("reasoning_profile", "fallback_policy", "resolution"):
            if not dispatch.get(field):
                errors.append(f"{prefix}: dispatch.strategy={strategy} requires dispatch.{field}")
        if all(dispatch.get(field) for field in ("reasoning_profile", "fallback_policy", "resolution")):
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
    surfaces = [s.lower() for s in evidence.get("verification", {}).get("changed_surface", [])]
    validate_quality_checks(
        task.get("quality_checks", {}),
        evidence.get("quality_checks", []),
        surfaces,
        artifact_index,
        enforce_verification,
        errors,
        prefix,
    )
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


def validate_project_coordinators(items: list[LoadedTask]) -> list[str]:
    owners: dict[Path, set[str]] = {}
    for item in items:
        heartbeat = (item.task.get("dispatch") or {}).get("heartbeat") or {}
        if heartbeat.get("status") != "active":
            continue
        owner = str(heartbeat.get("coordinator_thread_id") or "").removeprefix("codex-thread:")
        if owner:
            owners.setdefault(item.path.resolve().parent.parent, set()).add(owner)
    return [
        f"{project}: multiple active project Coordinators: {', '.join(sorted(ids))}; "
        "reconcile the established PM or complete a user-approved migration"
        for project, ids in owners.items()
        if len(ids) > 1
    ]


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
            if holder_run.get("status") == "provisioning":
                provisioning = holder_run.get("provisioning") or {}
                deadline = provisioning.get("deadline_at")
                if not deadline or parse_time(expires) > parse_time(deadline):
                    errors.append(
                        f"{item.path}: resource lock {lock.get('resource_id')} "
                        "outlives holder provisioning deadline"
                    )
                    continue
            else:
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
    profile = dispatch.get("reasoning_profile")
    fallback = dispatch.get("fallback_policy") or {}
    resolution = dispatch.get("resolution") or {}
    provider = resolution.get("provider")
    adapter = adapters.get(str(provider))
    if not adapter:
        errors.append(f"{prefix}: provider {provider!r} has no registered adapter")
        return

    if provider == "codex-subagent" and (dispatch.get("heartbeat_required") or dispatch.get("heartbeat")
                                         or "heartbeat" in dispatch.get("required_capabilities", [])):
        errors.append(f"{prefix}: native agents cannot satisfy periodic Heartbeat monitoring")

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

    historical_resolution = (
        task.get("status") in EVIDENCE_REQUIRED_STATUSES
        and not any(
            run.get("status") in ACTIVE_RUN_STATUSES for run in task.get("runs", [])
        )
    )
    if historical_resolution:
        if resolution.get("reasoning_profile") != profile:
            errors.append(f"{prefix}: resolution reasoning_profile differs from dispatch")
        return

    if resolution.get("adapter_version") != adapter.get("adapter_version"):
        errors.append(f"{prefix}: resolution adapter_version differs from provider adapter")
    if resolution.get("worker_type") not in adapter.get("worker_types", []):
        errors.append(f"{prefix}: provider {provider!r} does not support worker_type={resolution.get('worker_type')!r}")

    adapter_capabilities = set(adapter.get("capabilities", []))
    required_capabilities = set(dispatch.get("required_capabilities", []))
    resolved_capabilities = set(resolution.get("capabilities", []))
    effective_required = set(required_capabilities)
    non_heartbeat_monitor = (
        resolution.get("monitor_mode") in {"manual", "milestone", "event-lease"}
        and fallback.get("mode") == "compatible"
        and fallback.get("allow_manual_monitoring")
    )
    if resolution.get("monitor_mode") in {"milestone", "event-lease"} or non_heartbeat_monitor:
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

    if resolution.get("reasoning_profile") != profile:
        errors.append(f"{prefix}: resolution reasoning_profile differs from dispatch")
    components = adapter.get("components", {})
    model_component = components.get("model")
    model_route = (model_component or {}).get("profiles", {}).get(profile)
    if model_component:
        if not model_route:
            errors.append(f"{prefix}: provider {provider!r} does not map model route for reasoning_profile={profile!r}")
            expected_effort = None
        else:
            if resolution.get("model_id") != model_route.get("model_id"):
                errors.append(f"{prefix}: resolution model_id differs from adapter model route")
            expected_effort = model_route.get("reasoning_effort")
    else:
        if resolution.get("model_id") is not None:
            errors.append(f"{prefix}: provider {provider!r} does not declare model routing")
        expected_effort = components.get("reasoning", {}).get("profiles", {}).get(profile)
    if not expected_effort:
        errors.append(f"{prefix}: provider {provider!r} does not map reasoning_profile={profile!r}")
    elif resolution.get("provider_reasoning_effort") != expected_effort:
        errors.append(f"{prefix}: resolution provider_reasoning_effort differs from adapter mapping")

    monitor_modes = set(adapter.get("components", {}).get("monitor", {}).get("modes", []))
    monitor_mode = resolution.get("monitor_mode")
    if monitor_mode not in monitor_modes:
        errors.append(f"{prefix}: provider {provider!r} does not support monitor_mode={monitor_mode!r}")
    monitor = adapter.get("components", {}).get("monitor", {})
    if monitor_mode == "event-lease":
        if not monitor.get("supports_lease_renewal"):
            errors.append(f"{prefix}: event-lease monitoring requires lease renewal support")
        if not monitor.get("event_wait_target"):
            errors.append(f"{prefix}: event-lease monitoring requires an event_wait_target")
        event_capabilities = {"lease-watchdog", "terminal-event-wait"}
        if not event_capabilities.issubset(adapter_capabilities):
            errors.append(
                f"{prefix}: event-lease monitoring requires adapter capabilities: "
                f"{', '.join(sorted(event_capabilities))}"
            )
    if dispatch.get("heartbeat_required") and monitor_mode not in {"event-lease", "milestone", "heartbeat"}:
        manual_allowed = fallback.get("mode") == "compatible" and fallback.get("allow_manual_monitoring")
        if not (manual_allowed and monitor_mode == "manual"):
            errors.append(f"{prefix}: background monitoring was downgraded without compatible manual fallback")

    for run in task.get("runs", []):
        if run.get("status") not in ACTIVE_RUN_STATUSES:
            continue
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


def validate_quality_checks(
    task_quality: dict[str, Any],
    evidence_quality: list[dict[str, Any]],
    changed_surfaces: list[str],
    artifact_index: dict[str, dict[str, Any]],
    enforce_gate: bool,
    errors: list[str],
    prefix: str,
) -> None:
    task_checks: dict[str, dict[str, Any]] = {}
    for check in task_quality.get("checks", []):
        check_id = str(check.get("id") or "")
        if check_id in task_checks:
            errors.append(f"{prefix}: duplicate Task quality check {check_id!r}")
            continue
        task_checks[check_id] = check
        if check.get("requirement") == "conditional" and not check.get(
            "when_changed_surface"
        ):
            errors.append(
                f"{prefix}: conditional quality check {check_id!r} requires when_changed_surface"
            )

    evidence_checks: dict[str, dict[str, Any]] = {}
    for check in evidence_quality:
        check_id = str(check.get("id") or "")
        if check_id in evidence_checks:
            errors.append(f"{prefix}: duplicate Evidence quality check {check_id!r}")
            continue
        evidence_checks[check_id] = check
        if check_id not in task_checks:
            errors.append(
                f"{prefix}: Evidence quality check {check_id!r} is not declared by Task"
            )

    required_ids: set[str] = set()
    for check_id, task_check in task_checks.items():
        requirement = task_check.get("requirement")
        patterns = [
            str(pattern).lower()
            for pattern in task_check.get("when_changed_surface", [])
        ]
        triggered = any(
            matches_any(surface, patterns) for surface in changed_surfaces
        )
        required = requirement == "required" or (
            requirement == "conditional" and triggered
        )
        if required:
            required_ids.add(check_id)

        result = evidence_checks.get(check_id)
        if not result:
            if enforce_gate and required:
                errors.append(f"{prefix}: required quality check {check_id!r} is missing")
            continue

        result_status = result.get("status")
        if result_status == "passed":
            refs = result.get("evidence_refs") or []
            if not refs:
                errors.append(
                    f"{prefix}: passed quality check {check_id!r} requires evidence_refs"
                )
            if not result.get("tool") or not result.get("checked_at"):
                errors.append(
                    f"{prefix}: passed quality check {check_id!r} requires tool and checked_at"
                )
            allowed_kinds = set(task_check.get("evidence_kinds") or [])
            for evidence_ref in refs:
                artifact = artifact_index.get(str(evidence_ref))
                if not artifact:
                    errors.append(
                        f"{prefix}: quality check {check_id!r} evidence_ref "
                        f"{evidence_ref!r} does not match an artifact_id"
                    )
                elif artifact.get("result") != "pass":
                    errors.append(
                        f"{prefix}: quality check {check_id!r} references "
                        f"non-passing artifact {evidence_ref!r}"
                    )
                elif artifact.get("kind") not in allowed_kinds:
                    errors.append(
                        f"{prefix}: quality check {check_id!r} artifact {evidence_ref!r} "
                        f"uses kind={artifact.get('kind')!r}, expected one of "
                        f"{sorted(allowed_kinds)}"
                    )
        elif result_status == "skipped":
            if not result.get("skip_reason"):
                errors.append(
                    f"{prefix}: skipped quality check {check_id!r} requires skip_reason"
                )
            if enforce_gate and required:
                errors.append(
                    f"{prefix}: required quality check {check_id!r} cannot be skipped"
                )
        elif enforce_gate and result_status in {"failed", "blocked"}:
            errors.append(
                f"{prefix}: quality check {check_id!r} is {result_status} and blocks closure"
            )
        elif enforce_gate and required and result_status == "pending":
            errors.append(f"{prefix}: required quality check {check_id!r} is pending")

    if enforce_gate and not required_ids:
        errors.append(f"{prefix}: closure requires at least one required quality check")


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
    "maximum",
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
    profiles = (
        adapter.get("components", {})
        .get("reasoning", {})
        .get("profiles", {})
    )
    if not profiles:
        errors.append(f"{prefix}: reasoning component requires at least one profile mapping")

    model_component = adapter.get("components", {}).get("model")
    if model_component:
        model_profiles = model_component.get("profiles") or {}
        if set(model_profiles) != {"fast", "standard", "deep", "critical"}:
            errors.append(
                f"{prefix}: model component must map every core reasoning profile"
            )
        for profile, route in model_profiles.items():
            if not isinstance(route, dict) or not route.get("model_id"):
                errors.append(f"{prefix}: model route {profile!r} requires model_id")
            if not isinstance(route, dict) or route.get("complexity") not in {"simple", "complex"}:
                errors.append(f"{prefix}: model route {profile!r} requires simple/complex complexity")
            if not isinstance(route, dict) or not route.get("reasoning_effort"):
                errors.append(f"{prefix}: model route {profile!r} requires reasoning_effort")

    worker = adapter.get("components", {}).get("worker", {})
    operations = ("create", "send", "inspect", "wait", "rebind", "collect", "cancel")
    create = worker.get("create") or {}
    create_paths = create.get("result_paths") if isinstance(create, dict) else {}
    if isinstance(create_paths, dict) and not create_paths.get("worker_id"):
        errors.append(f"{prefix}: worker create operation requires result_paths.worker_id")
    if adapter.get("provider") == "codex-subagent":
        monitor = adapter.get("components", {}).get("monitor", {})
        if worker.get("visibility") != "internal" or worker.get("supports_background"):
            errors.append(f"{prefix}: native agents are internal, not durable background Workers")
        if monitor.get("modes") != ["milestone"] or monitor.get("supports_lease_renewal"):
            errors.append(f"{prefix}: native agents require parent milestone events without a watchdog")
        for name, target in {"create": "spawn_agent", "send": "send_input", "wait": "wait_agent", "cancel": "close_agent"}.items():
            if worker.get(name, {}).get("target") != target or worker.get(name, {}).get("supported") is False:
                errors.append(f"{prefix}: native agent {name} must use {target}")
        for name in ("inspect", "rebind", "collect"):
            if worker.get(name, {}).get("supported") is not False:
                errors.append(f"{prefix}: native agent {name} must not fabricate a callable tool")
        if worker.get("wait", {}).get("call_policy") != {
            "max_calls_per_run": 1, "max_timeout_ms": 30000, "allowed_sources": ["coordinator"]
        }:
            errors.append(f"{prefix}: native agent wait must use the single-short call policy")
    if adapter.get("provider") == "codex":
        if worker.get("visibility") != "user-visible":
            errors.append(f"{prefix}: Codex dispatch requires a user-visible Worker")
        if create.get("target") != "create_thread":
            errors.append(f"{prefix}: Codex visible Worker must be created with create_thread")
        inspect = worker.get("inspect") or {}
        wait = worker.get("wait") or {}
        if (
            inspect.get("target") != "wait_threads"
            or inspect.get("fixed_inputs") != {"timeout_ms": 0}
        ):
            errors.append(
                f"{prefix}: Codex inspect must be a zero-wait wait_threads snapshot"
            )
        if wait.get("target") != "wait_threads":
            errors.append(f"{prefix}: Codex terminal wait must use wait_threads")
        wait_required = set(wait.get("input_fields") or [])
        wait_optional = set(wait.get("optional_input_fields") or [])
        if "timeout_ms" not in wait_required or "timeout_ms" in wait_optional:
            errors.append(
                f"{prefix}: Codex terminal wait requires explicit timeout_ms"
            )
        expected_wait_policy = {
            "max_calls_per_run": CODEX_WAIT_MAX_CALLS_PER_RUN,
            "max_timeout_ms": CODEX_WAIT_MAX_TIMEOUT_MS,
            "allowed_sources": ["coordinator"],
        }
        if wait.get("call_policy") != expected_wait_policy:
            errors.append(
                f"{prefix}: Codex terminal wait must use the single-short call policy"
            )
        if wait.get("timeout_seconds") != CODEX_WAIT_MAX_TIMEOUT_MS // 1000:
            errors.append(f"{prefix}: Codex terminal wait transport timeout must be 30 seconds")
    for operation_name in operations:
        operation = worker.get(operation_name) or {}
        if not isinstance(operation, dict):
            continue
        required_inputs = set(operation.get("input_fields") or [])
        optional_inputs = set(operation.get("optional_input_fields") or [])
        fixed_inputs = operation.get("fixed_inputs") or {}
        if not isinstance(fixed_inputs, dict):
            errors.append(
                f"{prefix}: worker {operation_name}.fixed_inputs must be an object"
            )
            fixed_inputs = {}
        overlap = required_inputs & optional_inputs
        if overlap:
            errors.append(
                f"{prefix}: worker {operation_name} inputs cannot be both required and optional: "
                f"{', '.join(sorted(overlap))}"
            )
        fixed_overlap = (required_inputs | optional_inputs) & set(fixed_inputs)
        if fixed_overlap:
            errors.append(
                f"{prefix}: worker {operation_name} fixed inputs cannot be caller inputs: "
                f"{', '.join(sorted(fixed_overlap))}"
            )
        for path_field, value in (operation.get("result_paths") or {}).items():
            if value is not None and value != "$" and not str(value).startswith("$."):
                errors.append(
                    f"{prefix}: worker {operation_name}.result_paths.{path_field} "
                    "must use $ or a $. path"
                )
    status_map = adapter.get("status_map") or []
    provider_statuses = [item.get("provider_status") for item in status_map]
    if len(provider_statuses) != len(set(provider_statuses)):
        errors.append(f"{prefix}: status_map provider_status values must be unique")
    mapped_core_statuses = {item.get("core_status") for item in status_map}
    required_statuses = {"queued", "running", "succeeded", "failed", "blocked", "cancelled"}
    missing_statuses = required_statuses - mapped_core_statuses
    if missing_statuses:
        errors.append(
            f"{prefix}: status_map does not cover core statuses: "
            f"{', '.join(sorted(missing_statuses))}"
        )
    monitor = adapter.get("components", {}).get("monitor", {})
    if (
        adapter.get("provider") == "codex"
        and monitor.get("modes") != ["heartbeat"]
    ):
        errors.append(
            f"{prefix}: Codex visible Workers require heartbeat-only monitoring"
        )
    if "heartbeat" in set(monitor.get("modes") or []):
        if adapter.get("provider") == "codex" and monitor.get("heartbeat_operation") != "automation_update":
            errors.append(
                f"{prefix}: Codex heartbeat must be created with automation_update"
            )
        if monitor.get("heartbeat_target") != "coordinator-thread":
            errors.append(
                f"{prefix}: heartbeat monitor requires heartbeat_target=coordinator-thread"
            )
        if adapter.get("provider") == "codex" and monitor.get("coordinator_binding") != "current-conversation":
            errors.append(
                f"{prefix}: Codex heartbeat must bind to the current PM conversation"
            )
        if adapter.get("provider") == "codex" and int(
            str(adapter.get("adapter_version") or "0")
        ) >= CODEX_INSPECTION_POLICY_ADAPTER_VERSION:
            if monitor.get("inspection_interval_seconds") != INSPECTION_MIN_INTERVAL_SECONDS:
                errors.append(
                    f"{prefix}: Codex incremental inspection interval must equal 600 seconds"
                )
            if monitor.get("max_inspections_per_cycle") != INSPECTION_MAX_CALLS_PER_CYCLE:
                errors.append(
                    f"{prefix}: Codex incremental inspection allows one call per cycle"
                )
            if monitor.get("model_free_tick") != "scripts/plan_monitor_tick.py":
                errors.append(
                    f"{prefix}: Codex monitor must expose the model-free tick planner"
                )
    if "event-lease" in set(monitor.get("modes") or []):
        if not monitor.get("supports_lease_renewal"):
            errors.append(f"{prefix}: event-lease monitor requires supports_lease_renewal=true")
        if not monitor.get("event_wait_target"):
            errors.append(f"{prefix}: event-lease monitor requires event_wait_target")
        required = {"lease-watchdog", "terminal-event-wait"}
        missing = required - set(adapter.get("capabilities") or [])
        if missing:
            errors.append(
                f"{prefix}: event-lease monitor lacks capabilities: {', '.join(sorted(missing))}"
            )
    return errors


def latest_lease(run: dict[str, Any]) -> dict[str, Any] | None:
    attempts = run.get("attempts") or []
    for attempt in reversed(attempts):
        lease = attempt.get("lease")
        if lease:
            return lease
    return None


def validate_codex_inspection_policy(
    item: LoadedTask,
    errors: list[str],
    warnings: list[str],
    codex_session_dir: Path | None,
) -> None:
    prefix = str(item.path)
    authorizations = [
        event
        for event in item.runtime_events
        if event.get("event_type") == "status-inspect-authorized"
    ]
    observations = [
        event
        for event in item.runtime_events
        if event.get("event_type") == "status-observed"
        and (event.get("payload") or {}).get("authorization_event_id")
    ]
    runs_by_worker: dict[str, dict[str, Any]] = {}
    authorizations_by_run: dict[str, list[dict[str, Any]]] = {}
    for run in item.task.get("runs", []):
        if not inspection_policy_applies(run):
            continue
        run_id = str(run.get("run_id") or "")
        budget = run.get("inspection_budget")
        if not isinstance(budget, dict):
            errors.append(f"{prefix}: Codex v13+ run {run_id} requires inspection_budget")
            continue
        if budget.get("policy") != INSPECTION_POLICY_NAME:
            errors.append(
                f"{prefix}: run {run_id} inspection_budget.policy must be incremental-debounce"
            )
        if budget.get("min_interval_seconds") != INSPECTION_MIN_INTERVAL_SECONDS:
            errors.append(
                f"{prefix}: run {run_id} inspection interval must equal 600 seconds"
            )
        if budget.get("max_calls_per_cycle") != INSPECTION_MAX_CALLS_PER_CYCLE:
            errors.append(
                f"{prefix}: run {run_id} inspection max_calls_per_cycle must equal 1"
            )
        try:
            enforced_at = parse_time(budget.get("enforced_at"))
        except ValueError:
            continue
        run_events = sorted(
            [
                event
                for event in authorizations
                if event.get("run_id") == run_id
                and parse_time(event.get("occurred_at")) >= enforced_at
            ],
            key=lambda event: parse_time(event.get("occurred_at")),
        )
        authorizations_by_run[run_id] = run_events
        run_observations = [
            event for event in observations if event.get("run_id") == run_id
        ]
        authorization_ids = {
            str(event.get("event_id") or "") for event in run_events
        }
        for observation in run_observations:
            authorization_id = str(
                (observation.get("payload") or {}).get("authorization_event_id")
                or ""
            )
            if authorization_id not in authorization_ids:
                errors.append(
                    f"{prefix}: status observation {observation.get('event_id')} "
                    f"references unknown authorization {authorization_id!r}"
                )
        pending_ids = {
            str(event.get("event_id") or "")
            for event in pending_inspection_authorizations(item.runtime_events, run_id)
            if parse_time(event.get("occurred_at")) >= enforced_at
        }
        seen_cycles: set[str] = set()
        previous_authorization: datetime | None = None
        for index, event in enumerate(run_events):
            payload = event.get("payload") or {}
            cycle_id = str(payload.get("cycle_id") or "")
            source = payload.get("source")
            reason = payload.get("reason")
            occurred = parse_time(event.get("occurred_at"))
            if not cycle_id:
                errors.append(
                    f"{prefix}: status inspection {event.get('event_id')} requires cycle_id"
                )
            elif cycle_id in seen_cycles:
                errors.append(
                    f"{prefix}: run {run_id} inspection cycle {cycle_id!r} was consumed twice"
                )
            seen_cycles.add(cycle_id)
            if source not in {"coordinator", "heartbeat"}:
                errors.append(
                    f"{prefix}: status inspection {event.get('event_id')} has invalid source"
                )
            if reason not in {
                "post-create",
                "post-send",
                "scheduled",
                "user-request",
                "lease-risk",
            }:
                errors.append(
                    f"{prefix}: status inspection {event.get('event_id')} has invalid reason"
                )
            if source == "heartbeat" and reason not in {"scheduled", "lease-risk"}:
                errors.append(
                    f"{prefix}: Heartbeat inspection must be scheduled or lease-risk"
                )
            if payload.get("timeout_ms") != 0:
                errors.append(f"{prefix}: status inspection authorization must use timeout_ms=0")
            if event.get("provider") != "codex" or event.get("worker_id") != run.get("worker_id"):
                errors.append(
                    f"{prefix}: status inspection must match run {run_id} Codex Worker"
                )
            matches = [
                observation
                for observation in run_observations
                if (observation.get("payload") or {}).get(
                    "authorization_event_id"
                )
                == event.get("event_id")
            ]
            if len(matches) > 1:
                errors.append(
                    f"{prefix}: status inspection {event.get('event_id')} was observed more than once"
                )
            elif matches and parse_time(matches[0].get("occurred_at")) < occurred:
                errors.append(
                    f"{prefix}: status observation predates authorization {event.get('event_id')}"
                )
            elif event.get("event_id") in pending_ids:
                if index < len(run_events) - 1:
                    errors.append(
                        f"{prefix}: status inspection {event.get('event_id')} was not reconciled "
                        "before another snapshot was authorized"
                    )
                else:
                    warnings.append(
                        f"{prefix}: latest status inspection {event.get('event_id')} awaits reconciliation"
                    )
            if reason == "scheduled":
                if previous_authorization and (
                    occurred - previous_authorization
                ).total_seconds() < INSPECTION_MIN_INTERVAL_SECONDS:
                    errors.append(
                        f"{prefix}: run {run_id} scheduled inspections are less than 600 seconds apart"
                    )
            previous_authorization = occurred
        worker_id = str(run.get("worker_id") or "")
        if worker_id:
            runs_by_worker[worker_id] = run
            runs_by_worker[codex_thread_id(worker_id)] = run

    if codex_session_dir and runs_by_worker:
        validate_codex_inspection_session_audit(
            item,
            codex_session_dir,
            runs_by_worker,
            authorizations_by_run,
            errors,
            warnings,
        )


def validate_codex_inspection_session_audit(
    item: LoadedTask,
    session_dir: Path,
    runs_by_worker: dict[str, dict[str, Any]],
    authorizations_by_run: dict[str, list[dict[str, Any]]],
    errors: list[str],
    warnings: list[str],
) -> None:
    prefix = str(item.path)
    heartbeat = item.task.get("dispatch", {}).get("heartbeat") or {}
    coordinator_id = str(heartbeat.get("coordinator_thread_id") or "")
    if not coordinator_id:
        return
    if session_dir.is_file():
        session_files = [session_dir]
    elif session_dir.exists():
        session_files = sorted(
            session_dir.rglob(f"*{codex_thread_id(coordinator_id)}*.jsonl")
        )
    else:
        session_files = []
    if not session_files:
        warnings.append(
            f"{prefix}: no Codex session log found for inspection audit of {coordinator_id!r}"
        )
        return
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in session_files:
        for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "wait_threads" not in raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            parsed = codex_wait_call_from_session_record(record, path, lineno)
            if parsed is None:
                continue
            call_id, arguments = parsed
            if call_id in seen or arguments.get("timeoutMs") != 0:
                continue
            seen.add(call_id)
            try:
                occurred_at = parse_time(record.get("timestamp"))
            except ValueError:
                continue
            for target in arguments.get("targets") or []:
                worker_id = str(target.get("threadId") or "")
                run = runs_by_worker.get(worker_id) or runs_by_worker.get(
                    codex_thread_id(worker_id)
                )
                if not run:
                    continue
                budget = run.get("inspection_budget") or {}
                try:
                    enforced_at = parse_time(budget.get("enforced_at"))
                except ValueError:
                    continue
                if occurred_at >= enforced_at:
                    calls.append(
                        {
                            "call_id": call_id,
                            "run_id": run.get("run_id"),
                            "worker_id": run.get("worker_id"),
                            "occurred_at": occurred_at,
                        }
                    )
    used: set[str] = set()
    for call in sorted(calls, key=lambda value: value["occurred_at"]):
        match = next(
            (
                event
                for event in authorizations_by_run.get(str(call["run_id"]), [])
                if str(event.get("event_id")) not in used
                and event.get("worker_id") == call["worker_id"]
                and parse_time(event.get("occurred_at")) <= call["occurred_at"]
            ),
            None,
        )
        if not match:
            errors.append(
                f"{prefix}: unpermitted zero-wait wait_threads call {call['call_id']} "
                f"for run {call['run_id']}"
            )
            continue
        used.add(str(match.get("event_id")))


def validate_codex_wait_policy(
    item: LoadedTask,
    errors: list[str],
    warnings: list[str],
    codex_session_dir: Path | None,
) -> None:
    prefix = str(item.path)
    authorizations = [
        event
        for event in item.runtime_events
        if event.get("event_type") == "terminal-wait-authorized"
    ]
    completions = [
        event
        for event in item.runtime_events
        if event.get("event_type") == "terminal-wait-finished"
    ]
    authorizations_by_id = {
        str(event.get("event_id")): event for event in authorizations
    }
    authorization_ids = set(authorizations_by_id)
    completed_authorizations: set[str] = set()
    for event in completions:
        authorization_id = str((event.get("payload") or {}).get("authorization_event_id") or "")
        if authorization_id not in authorization_ids:
            errors.append(
                f"{prefix}: terminal-wait-finished references unknown authorization "
                f"{authorization_id!r}"
            )
        elif authorization_id in completed_authorizations:
            errors.append(
                f"{prefix}: terminal wait authorization {authorization_id!r} completed twice"
            )
        else:
            authorization = authorizations_by_id[authorization_id]
            for field in ("run_id", "attempt_id", "provider", "worker_id"):
                if event.get(field) != authorization.get(field):
                    errors.append(
                        f"{prefix}: terminal-wait-finished {event.get('event_id')!r} "
                        f"must match authorization {authorization_id!r} field {field}"
                    )
            if parse_time(event.get("occurred_at")) < parse_time(
                authorization.get("occurred_at")
            ):
                errors.append(
                    f"{prefix}: terminal-wait-finished {event.get('event_id')!r} "
                    "predates its authorization"
                )
            if (event.get("payload") or {}).get("outcome") not in {
                "completed",
                "timeout",
                "call-error",
            }:
                errors.append(
                    f"{prefix}: terminal-wait-finished {event.get('event_id')!r} "
                    "requires outcome completed, timeout, or call-error"
                )
        completed_authorizations.add(authorization_id)

    for run in item.task.get("runs", []):
        if not codex_wait_policy_applies(run):
            continue
        run_id = str(run.get("run_id") or "")
        budget = run.get("wait_budget")
        if not isinstance(budget, dict):
            errors.append(f"{prefix}: Codex v12 run {run_id} requires wait_budget")
            continue
        if budget.get("policy") != CODEX_WAIT_POLICY_NAME:
            errors.append(f"{prefix}: run {run_id} wait_budget.policy must be single-short")
        if budget.get("max_calls") != CODEX_WAIT_MAX_CALLS_PER_RUN:
            errors.append(f"{prefix}: run {run_id} wait_budget.max_calls must equal 1")
        if budget.get("max_timeout_ms") != CODEX_WAIT_MAX_TIMEOUT_MS:
            errors.append(f"{prefix}: run {run_id} wait_budget.max_timeout_ms must equal 30000")
        try:
            enforced_at = parse_time(budget.get("enforced_at"))
        except ValueError:
            continue
        run_authorizations = [
            event
            for event in authorizations
            if event.get("run_id") == run_id
            and parse_time(event.get("occurred_at")) >= enforced_at
        ]
        if len(run_authorizations) > CODEX_WAIT_MAX_CALLS_PER_RUN:
            errors.append(
                f"{prefix}: run {run_id} consumed {len(run_authorizations)} terminal waits; maximum is 1"
            )
        snapshots = [
            event
            for event in item.runtime_events
            if event.get("event_type") == "status-observed"
            and event.get("run_id") == run_id
            and event.get("worker_id") == run.get("worker_id")
            and parse_time(event.get("occurred_at")) >= enforced_at
            and (event.get("payload") or {}).get("operation") == "inspect"
            and (event.get("payload") or {}).get("timeout_ms") == 0
            and (event.get("payload") or {}).get("source") == "coordinator"
        ]
        for event in run_authorizations:
            payload = event.get("payload") or {}
            timeout_ms = payload.get("timeout_ms")
            if payload.get("source") != "coordinator":
                errors.append(
                    f"{prefix}: run {run_id} positive terminal wait cannot originate from Heartbeat"
                )
            if (
                not isinstance(timeout_ms, int)
                or isinstance(timeout_ms, bool)
                or timeout_ms < (10000 if run.get("provider") == "codex-subagent" else 1)
                or timeout_ms > CODEX_WAIT_MAX_TIMEOUT_MS
            ):
                errors.append(
                    f"{prefix}: run {run_id} terminal wait timeout must be within 1..30000 ms"
                )
            if event.get("provider") != run.get("provider") or event.get("worker_id") != run.get("worker_id"):
                errors.append(
                    f"{prefix}: run {run_id} terminal wait authorization must match its Codex Worker"
                )
            if run.get("provider") == "codex" and not any(
                parse_time(snapshot.get("occurred_at"))
                <= parse_time(event.get("occurred_at"))
                for snapshot in snapshots
            ):
                errors.append(
                    f"{prefix}: run {run_id} terminal wait requires a prior coordinator zero-wait snapshot"
                )

    if codex_session_dir:
        validate_codex_wait_session_audit(
            item,
            codex_session_dir,
            authorizations,
            errors,
            warnings,
        )


def validate_codex_wait_session_audit(
    item: LoadedTask,
    session_dir: Path,
    authorizations: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> None:
    heartbeat = item.task.get("dispatch", {}).get("heartbeat") or {}
    coordinator_id = str(heartbeat.get("coordinator_thread_id") or "")
    if not coordinator_id:
        return
    if not session_dir.exists():
        warnings.append(f"{item.path}: Codex session audit directory is unavailable: {session_dir}")
        return
    if session_dir.is_file():
        session_files = [session_dir]
    else:
        coordinator_lookup = codex_thread_id(coordinator_id)
        session_files = sorted(session_dir.rglob(f"*{coordinator_lookup}*.jsonl"))
    if not session_files:
        warnings.append(
            f"{item.path}: no Codex session log found for coordinator {coordinator_id!r}"
        )
        return

    runs_by_worker: dict[str, dict[str, Any]] = {}
    for run in item.task.get("runs", []):
        worker_id = str(run.get("worker_id") or "")
        if not worker_id or not codex_wait_policy_applies(run):
            continue
        runs_by_worker[worker_id] = run
        runs_by_worker[codex_thread_id(worker_id)] = run
    calls: list[dict[str, Any]] = []
    seen_call_ids: set[str] = set()
    for path in session_files:
        for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "wait_threads" not in raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            call = codex_wait_call_from_session_record(record, path, lineno)
            if call is None:
                continue
            call_id, arguments = call
            if call_id in seen_call_ids:
                continue
            seen_call_ids.add(call_id)
            timeout_ms = arguments.get("timeoutMs")
            if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
                continue
            try:
                occurred_at = parse_time(record.get("timestamp"))
            except ValueError:
                continue
            for target in arguments.get("targets") or []:
                worker_id = str(target.get("threadId") or "")
                run = runs_by_worker.get(worker_id) or runs_by_worker.get(
                    codex_thread_id(worker_id)
                )
                if not run:
                    continue
                budget = run.get("wait_budget") or {}
                try:
                    enforced_at = parse_time(budget.get("enforced_at"))
                except ValueError:
                    continue
                if occurred_at < enforced_at:
                    continue
                calls.append(
                    {
                        "call_id": call_id,
                        "run_id": run.get("run_id"),
                        "worker_id": run.get("worker_id"),
                        "timeout_ms": timeout_ms,
                        "occurred_at": occurred_at,
                        "enforced_at": enforced_at,
                    }
                )

    used_authorizations: set[str] = set()
    for call in sorted(calls, key=lambda value: value["occurred_at"]):
        match = next(
            (
                event
                for event in authorizations
                if str(event.get("event_id")) not in used_authorizations
                and event.get("run_id") == call["run_id"]
                and event.get("worker_id") == call["worker_id"]
                and (event.get("payload") or {}).get("source") == "coordinator"
                and (event.get("payload") or {}).get("timeout_ms") == call["timeout_ms"]
                and parse_time(event.get("occurred_at")) >= call["enforced_at"]
                and parse_time(event.get("occurred_at")) <= call["occurred_at"]
            ),
            None,
        )
        if not match:
            errors.append(
                f"{item.path}: unpermitted positive wait_threads call {call['call_id']} "
                f"for run {call['run_id']} timeoutMs={call['timeout_ms']}"
            )
            continue
        used_authorizations.add(str(match.get("event_id")))


def codex_thread_id(value: str) -> str:
    return value.removeprefix("codex-thread:")


def codex_wait_call_from_session_record(
    record: dict[str, Any], path: Path, lineno: int
) -> tuple[str, dict[str, Any]] | None:
    """Read the structured wait_threads completion emitted by Codex rollout logs."""
    payload = record.get("payload") or {}
    item = payload.get("item") or {}
    if (
        record.get("type") == "event_msg"
        and payload.get("type") == "item_completed"
        and item.get("type") == "McpToolCall"
        and item.get("server") == "codex_app"
        and item.get("tool") == "wait_threads"
    ):
        call_id = str(item.get("id") or f"{path}:{lineno}")
        return call_id, item.get("arguments") or {}

    # Retain compatibility with the early v12 audit fixture format.
    invocation = payload.get("invocation") or {}
    if (
        record.get("type") == "event_msg"
        and payload.get("type") == "mcp_tool_call_end"
        and invocation.get("server") == "codex_app"
        and invocation.get("tool") == "wait_threads"
    ):
        call_id = str(payload.get("call_id") or f"{path}:{lineno}")
        return call_id, invocation.get("arguments") or {}
    return None


def validate_codex_heartbeat_automation(
    heartbeat: dict[str, Any],
    automation_dir: Path,
    errors: list[str],
    prefix: str,
) -> None:
    automation_id = str(heartbeat.get("automation_id") or "")
    automation_path = (automation_dir / automation_id / "automation.toml").resolve()
    try:
        automation_path.relative_to(automation_dir)
    except ValueError:
        errors.append(f"{prefix}: heartbeat automation_id escapes automation directory")
        return

    task_status = str(heartbeat.get("status") or "").lower()
    if not automation_path.exists():
        if task_status == "active":
            errors.append(
                f"{prefix}: active heartbeat automation is missing: {automation_path}"
            )
        return

    try:
        with automation_path.open("rb") as handle:
            automation = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"{prefix}: cannot load heartbeat automation {automation_path}: {exc}")
        return

    actual_status = str(automation.get("status") or "").lower()
    if task_status == "active" and actual_status != "active":
        errors.append(
            f"{prefix}: Task heartbeat status active differs from Automation status "
            f"{actual_status or 'missing'}"
        )
    elif task_status in {"paused", "stopped"} and actual_status == "active":
        errors.append(
            f"{prefix}: Task heartbeat status {task_status} differs from Automation status active"
        )

    if str(automation.get("kind") or "") != "heartbeat":
        errors.append(f"{prefix}: heartbeat Automation kind must equal heartbeat")
    expected_coordinator = str(heartbeat.get("coordinator_thread_id") or "")
    actual_target = str(automation.get("target_thread_id") or "")
    if actual_target != expected_coordinator:
        errors.append(
            f"{prefix}: heartbeat coordinator_thread_id {expected_coordinator!r} differs from "
            f"Automation target_thread_id {actual_target!r}"
        )
    prompt = str(automation.get("prompt") or "").strip()
    configured_budget = heartbeat.get("prompt_max_chars")
    prompt_budget = (
        min(configured_budget, HEARTBEAT_PROMPT_MAX_CHARS)
        if isinstance(configured_budget, int) and not isinstance(configured_budget, bool)
        else HEARTBEAT_PROMPT_MAX_CHARS
    )
    if not prompt:
        errors.append(f"{prefix}: heartbeat Automation prompt must not be empty")
    elif len(prompt) > prompt_budget:
        errors.append(
            f"{prefix}: heartbeat Automation prompt has {len(prompt)} chars; "
            f"maximum is {prompt_budget}"
        )

    rrule = str(automation.get("rrule") or "")
    if not re.search(r"(?:^|;)FREQ=MINUTELY(?:;|$)", rrule):
        errors.append(f"{prefix}: heartbeat Automation RRULE must use FREQ=MINUTELY")
        return
    interval_match = re.search(r"(?:^|;)INTERVAL=([0-9]+)(?:;|$)", rrule)
    if not interval_match:
        errors.append(f"{prefix}: heartbeat Automation RRULE has no minute interval")
        return
    actual_interval = int(interval_match.group(1))
    expected_interval = int(heartbeat["interval_minutes"])
    if actual_interval != expected_interval:
        errors.append(
            f"{prefix}: Task heartbeat interval {expected_interval} differs from "
            f"Automation interval {actual_interval}"
        )


def matches_any(value: str, needles: list[str]) -> bool:
    return any(needle in value for needle in needles)


def design_freeze_fingerprint(freeze: dict[str, Any]) -> str:
    payload = {
        "scope": freeze.get("scope") or [],
        "constraints": freeze.get("constraints") or [],
        "acceptance": freeze.get("acceptance") or [],
        "change_policy": freeze.get("change_policy"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


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
    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        errors.append(f"{path}: value must be <= {schema['maximum']}")
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

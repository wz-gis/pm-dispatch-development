#!/usr/bin/env python3
"""Authorize one debounced zero-wait Worker status snapshot."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from adapter_protocol import build_invocation  # noqa: E402
from monitor_policy import (  # noqa: E402
    INSPECTION_MAX_CALLS_PER_CYCLE,
    INSPECTION_MIN_INTERVAL_SECONDS,
    INSPECTION_POLICY_NAME,
    inspection_policy_applies,
    pending_inspection_authorizations,
)
from record_runtime_event import resolve_runtime_path  # noqa: E402
from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_structured_file,
    parse_time,
    validate_schema,
)


ACTIVE_STATUSES = {"queued", "running"}
REASONS = {"post-create", "post-send", "scheduled", "user-request", "lease-risk"}


class StatusInspectAuthorizationError(ValueError):
    """Raised when a zero-wait snapshot would violate its Run budget."""


def event_log_path(runtime_path: Path, runtime: dict[str, Any]) -> Path:
    configured_value = str(runtime.get("event_log_file") or "").strip()
    if not configured_value:
        raise StatusInspectAuthorizationError("Runtime requires event_log_file")
    configured = Path(configured_value)
    return configured if configured.is_absolute() else (runtime_path.parent / configured).resolve()


def load_events(stream: Any, schema: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    stream.seek(0)
    result: list[dict[str, Any]] = []
    for lineno, line in enumerate(stream.read().splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StatusInspectAuthorizationError(
                f"invalid event log {path}:{lineno}: {exc}"
            ) from exc
        errors = validate_schema(event, schema, f"{path}:{lineno}", schema)
        if errors:
            raise StatusInspectAuthorizationError("; ".join(errors))
        result.append(event)
    return result


def authorize_status_inspect(
    runtime_path: Path,
    *,
    run_id: str,
    source: str,
    reason: str,
    cycle_id: str,
    event_id: str,
    occurred_at: str,
    adapter: dict[str, Any],
    event_schema: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    runtime = load_structured_file(runtime_path)
    run = next(
        (item for item in runtime.get("runs", []) if item.get("run_id") == run_id),
        None,
    )
    if not isinstance(run, dict) or run.get("status") not in ACTIVE_STATUSES:
        raise StatusInspectAuthorizationError("status inspection requires an executing Run")
    worker_id = str(run.get("worker_id") or "")
    if not worker_id:
        raise StatusInspectAuthorizationError("status inspection requires worker_id")
    if not inspection_policy_applies(run):
        raise StatusInspectAuthorizationError("Run does not use the Codex v13+ inspection policy")
    budget = run.get("inspection_budget")
    if not isinstance(budget, dict) or budget.get("policy") != INSPECTION_POLICY_NAME:
        raise StatusInspectAuthorizationError("Codex v13+ Run requires inspection_budget")
    if (
        budget.get("min_interval_seconds") != INSPECTION_MIN_INTERVAL_SECONDS
        or budget.get("max_calls_per_cycle") != INSPECTION_MAX_CALLS_PER_CYCLE
    ):
        raise StatusInspectAuthorizationError("Run inspection_budget differs from Codex v13+ policy")
    if reason not in REASONS:
        raise StatusInspectAuthorizationError(f"unsupported inspection reason {reason!r}")
    if source == "heartbeat" and reason not in {"scheduled", "lease-risk"}:
        raise StatusInspectAuthorizationError(
            "Heartbeat inspection reason must be scheduled or lease-risk"
        )
    heartbeat = runtime.get("heartbeat")
    if not isinstance(heartbeat, dict) or heartbeat.get("status") != "active":
        raise StatusInspectAuthorizationError("status inspection requires active Heartbeat")
    if heartbeat.get("target_run_id") != run_id:
        raise StatusInspectAuthorizationError("Heartbeat must target the inspected Run")

    active_attempts = [
        attempt
        for attempt in run.get("attempts", [])
        if attempt.get("status") in ACTIVE_STATUSES
    ]
    if len(active_attempts) != 1:
        raise StatusInspectAuthorizationError("status inspection requires one active Attempt")
    occurred = parse_time(occurred_at)
    enforced_at = parse_time(budget.get("enforced_at"))
    if occurred < enforced_at:
        raise StatusInspectAuthorizationError("inspection predates inspection_budget.enforced_at")
    event_cursor = run.get("event_cursor")
    event = {
        "schema_version": "1",
        "event_id": event_id,
        "event_type": "status-inspect-authorized",
        "task_id": runtime.get("task_id"),
        "occurred_at": occurred_at,
        "run_id": run_id,
        "attempt_id": active_attempts[0].get("attempt_id"),
        "provider": "codex",
        "worker_id": worker_id,
        "payload": {
            "source": source,
            "reason": reason,
            "cycle_id": cycle_id,
            "timeout_ms": 0,
            "event_cursor": event_cursor,
        },
    }
    event_errors = validate_schema(event, event_schema, "event", event_schema)
    if event_errors:
        raise StatusInspectAuthorizationError("; ".join(event_errors))

    path = event_log_path(runtime_path, runtime)
    if not path.exists():
        raise StatusInspectAuthorizationError(f"event log does not exist: {path}")
    with path.open("r+" if write else "r", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        events = load_events(stream, event_schema, path)
        if any(item.get("event_id") == event_id for item in events):
            raise StatusInspectAuthorizationError(f"duplicate event_id {event_id!r}")
        if events and occurred < parse_time(events[-1].get("occurred_at")):
            raise StatusInspectAuthorizationError("inspection is earlier than event log tail")
        prior = [
            item
            for item in events
            if item.get("event_type") == "status-inspect-authorized"
            and item.get("run_id") == run_id
            and parse_time(item.get("occurred_at")) >= enforced_at
        ]
        used_in_cycle = sum(
            1 for item in prior if (item.get("payload") or {}).get("cycle_id") == cycle_id
        )
        if used_in_cycle >= int(budget["max_calls_per_cycle"]):
            raise StatusInspectAuthorizationError(
                f"inspection cycle {cycle_id!r} already consumed its budget"
            )
        pending = pending_inspection_authorizations(events, run_id)
        if pending:
            raise StatusInspectAuthorizationError(
                "previous status inspection has no persisted status-observed result: "
                f"{pending[-1].get('event_id')}; reconcile it before another snapshot"
            )
        if reason == "scheduled" and prior:
            elapsed = (occurred - parse_time(prior[-1].get("occurred_at"))).total_seconds()
            if elapsed < int(budget["min_interval_seconds"]):
                remaining = int(budget["min_interval_seconds"] - elapsed)
                raise StatusInspectAuthorizationError(
                    f"scheduled inspection is debounced for another {remaining} seconds"
                )
        if write:
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    inputs: dict[str, Any] = {"worker_id": worker_id}
    native_target: dict[str, Any] = {"threadId": worker_id}
    if event_cursor:
        inputs["event_cursor"] = event_cursor
        native_target["afterCursor"] = event_cursor
    return {
        "authorization": event,
        "adapter_envelope": build_invocation(adapter, "inspect", inputs, source=source),
        "native_arguments": {"targets": [native_target], "timeoutMs": 0},
        "written": write,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize one zero-wait Worker snapshot.")
    parser.add_argument("document")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source", choices=["coordinator", "heartbeat"], default="coordinator")
    parser.add_argument("--reason", choices=sorted(REASONS), required=True)
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--now")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    runtime_path = resolve_runtime_path(Path(args.document).resolve())
    root = SCRIPT_DIR.parent
    adapter = load_structured_file(root / "references" / "adapters" / "codex.adapter.json")
    event_schema = load_structured_file(root / "references" / "schemas" / "runtime-event.schema.json")
    assert_supported_schema(event_schema, "runtime-event.schema.json")
    result = authorize_status_inspect(
        runtime_path,
        run_id=args.run_id,
        source=args.source,
        reason=args.reason,
        cycle_id=args.cycle_id,
        event_id=args.event_id,
        occurred_at=args.now
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        adapter=adapter,
        event_schema=event_schema,
        write=args.write,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, StatusInspectAuthorizationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Persist one authorized Worker snapshot and reconcile its Runtime atomically enough."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from reconcile_worker_liveness import atomic_write, reconcile_liveness  # noqa: E402
from record_runtime_event import append_event, resolve_runtime_path  # noqa: E402
from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_structured_file,
    parse_time,
)


class InspectionCompletionError(ValueError):
    """Raised when an inspection result cannot consume exactly one authorization."""


def event_log_path(runtime_path: Path, runtime: dict[str, Any]) -> Path:
    configured_value = str(runtime.get("event_log_file") or "").strip()
    if not configured_value:
        raise InspectionCompletionError("Runtime requires event_log_file")
    configured = Path(configured_value)
    return configured if configured.is_absolute() else (runtime_path.parent / configured).resolve()


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise InspectionCompletionError(f"event log does not exist: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def complete_inspection(
    runtime_path: Path,
    *,
    authorization_event_id: str,
    event_id: str,
    probe_status: str,
    latest_turn_status: str | None,
    terminal_outcome: str | None,
    event_cursor: str | None,
    occurred_at: str,
    event_schema: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    runtime = load_structured_file(runtime_path)
    events_path = event_log_path(runtime_path, runtime)
    events = load_events(events_path)
    authorization = next(
        (
            event
            for event in events
            if event.get("event_id") == authorization_event_id
            and event.get("event_type") == "status-inspect-authorized"
        ),
        None,
    )
    if not authorization:
        raise InspectionCompletionError("status inspection authorization was not found")
    if any(
        event.get("event_type") == "status-observed"
        and (event.get("payload") or {}).get("authorization_event_id")
        == authorization_event_id
        for event in events
    ):
        raise InspectionCompletionError("status inspection authorization was already consumed")
    run_id = str(authorization.get("run_id") or "")
    if not run_id:
        raise InspectionCompletionError("status inspection authorization has no run_id")
    occurred = parse_time(occurred_at)
    if occurred < parse_time(authorization.get("occurred_at")):
        raise InspectionCompletionError("status observation predates its authorization")

    reconciled, outcome = reconcile_liveness(
        runtime,
        run_id,
        probe_status,
        occurred,
        latest_turn_status=latest_turn_status,
        terminal_outcome=terminal_outcome,
    )
    run = next(item for item in reconciled.get("runs", []) if item.get("run_id") == run_id)
    if event_cursor is not None:
        run["event_cursor"] = event_cursor
        attempts = run.get("attempts") or []
        if attempts and isinstance(attempts[-1].get("lease"), dict):
            attempts[-1]["lease"]["event_cursor"] = event_cursor
    event = {
        "schema_version": "1",
        "event_id": event_id,
        "event_type": "status-observed",
        "task_id": reconciled.get("task_id"),
        "occurred_at": occurred_at,
        "run_id": run_id,
        "attempt_id": authorization.get("attempt_id"),
        "provider": authorization.get("provider"),
        "worker_id": authorization.get("worker_id"),
        "payload": {
            "authorization_event_id": authorization_event_id,
            "provider_status": probe_status,
            "latest_turn_status": latest_turn_status,
            "terminal_outcome": terminal_outcome,
            "outcome": outcome,
            "event_cursor": event_cursor,
        },
    }
    append_event(runtime_path, event, event_schema, False)
    if write:
        atomic_write(runtime_path, reconciled)
        append_event(runtime_path, event, event_schema, True)
    required_host_action = (
        "collect-once-then-pause-heartbeat"
        if outcome.startswith("terminal-")
        else "none"
    )
    return {
        "outcome": outcome,
        "required_host_action": required_host_action,
        "event": event,
        "runtime": reconciled,
        "written": write,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Complete one authorized Worker status snapshot.")
    parser.add_argument("document")
    parser.add_argument("--authorization-event-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument(
        "--probe-status",
        required=True,
        choices=["running", "queued", "idle", "interrupted", "succeeded", "failed", "blocked", "cancelled", "monitor-unavailable", "unreachable"],
    )
    parser.add_argument("--latest-turn-status", choices=["running", "completed", "failed", "interrupted"])
    parser.add_argument("--terminal-outcome", choices=["succeeded", "failed", "blocked", "cancelled"])
    parser.add_argument("--event-cursor")
    parser.add_argument("--now")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    runtime_path = resolve_runtime_path(Path(args.document).resolve())
    schema = load_structured_file(SCRIPT_DIR.parent / "references" / "schemas" / "runtime-event.schema.json")
    assert_supported_schema(schema, "runtime-event.schema.json")
    lock_path = runtime_path.with_name(runtime_path.name + ".inspection.lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if args.write else fcntl.LOCK_SH)
        result = complete_inspection(
            runtime_path,
            authorization_event_id=args.authorization_event_id,
            event_id=args.event_id,
            probe_status=args.probe_status,
            latest_turn_status=args.latest_turn_status,
            terminal_outcome=args.terminal_outcome,
            event_cursor=args.event_cursor,
            occurred_at=args.now or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            event_schema=schema,
            write=args.write,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, InspectionCompletionError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

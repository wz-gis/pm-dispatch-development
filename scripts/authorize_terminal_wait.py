#!/usr/bin/env python3
"""Atomically consume one Run's short terminal-wait budget."""

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
from record_runtime_event import resolve_runtime_path  # noqa: E402
from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_structured_file,
    parse_time,
    validate_schema,
)
from wait_policy import (  # noqa: E402
    CODEX_WAIT_MAX_CALLS_PER_RUN,
    CODEX_WAIT_MAX_TIMEOUT_MS,
    CODEX_WAIT_POLICY_NAME,
    codex_wait_policy_applies,
)


ACTIVE_STATUSES = {"queued", "running"}


class TerminalWaitAuthorizationError(ValueError):
    """Raised when a positive wait would violate the Run budget."""


def event_log_path(runtime_path: Path, runtime: dict[str, Any]) -> Path:
    configured_value = str(runtime.get("event_log_file") or "").strip()
    if not configured_value:
        raise TerminalWaitAuthorizationError("Runtime requires event_log_file")
    configured = Path(configured_value)
    return configured if configured.is_absolute() else (runtime_path.parent / configured).resolve()


def find_active_run(runtime: dict[str, Any], run_id: str) -> dict[str, Any]:
    run = next((item for item in runtime.get("runs", []) if item.get("run_id") == run_id), None)
    if not isinstance(run, dict):
        raise TerminalWaitAuthorizationError(f"unknown run_id {run_id!r}")
    if run.get("status") not in ACTIVE_STATUSES:
        raise TerminalWaitAuthorizationError("terminal wait requires an active Run")
    if not run.get("worker_id"):
        raise TerminalWaitAuthorizationError("terminal wait requires a real worker_id")
    if not codex_wait_policy_applies(run):
        raise TerminalWaitAuthorizationError("Run does not use the Codex v12 wait policy")
    return run


def validate_wait_budget(run: dict[str, Any], timeout_ms: int, source: str) -> dict[str, Any]:
    if source != "coordinator":
        raise TerminalWaitAuthorizationError("Heartbeat cannot authorize a positive terminal wait")
    if isinstance(timeout_ms, bool) or timeout_ms <= 0:
        raise TerminalWaitAuthorizationError("terminal wait timeout_ms must be positive")
    budget = run.get("wait_budget")
    if not isinstance(budget, dict):
        raise TerminalWaitAuthorizationError("Codex v12 active Run requires wait_budget")
    if (
        budget.get("policy") != CODEX_WAIT_POLICY_NAME
        or budget.get("max_calls") != CODEX_WAIT_MAX_CALLS_PER_RUN
        or budget.get("max_timeout_ms") != CODEX_WAIT_MAX_TIMEOUT_MS
    ):
        raise TerminalWaitAuthorizationError("Run wait_budget differs from Codex v12 policy")
    if timeout_ms > int(budget["max_timeout_ms"]):
        raise TerminalWaitAuthorizationError(
            f"terminal wait timeout_ms exceeds {budget['max_timeout_ms']}"
        )
    parse_time(budget.get("enforced_at"))
    return budget


def validate_heartbeat(runtime: dict[str, Any], run_id: str) -> None:
    heartbeat = runtime.get("heartbeat")
    if not isinstance(heartbeat, dict):
        raise TerminalWaitAuthorizationError("terminal wait requires coordinator Heartbeat")
    if heartbeat.get("status") != "active":
        raise TerminalWaitAuthorizationError("terminal wait requires heartbeat.status=active")
    if heartbeat.get("target_run_id") != run_id:
        raise TerminalWaitAuthorizationError("Heartbeat must target the waiting Run")
    if not heartbeat.get("coordinator_thread_id"):
        raise TerminalWaitAuthorizationError("Heartbeat requires coordinator_thread_id")


def parse_events(stream: Any, event_schema: dict[str, Any], event_path: Path) -> list[dict[str, Any]]:
    stream.seek(0)
    events: list[dict[str, Any]] = []
    for lineno, raw_line in enumerate(stream.read().splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise TerminalWaitAuthorizationError(
                f"invalid event log {event_path}:{lineno}: {exc}"
            ) from exc
        errors = validate_schema(event, event_schema, f"{event_path}:{lineno}", event_schema)
        if errors:
            raise TerminalWaitAuthorizationError("; ".join(errors))
        events.append(event)
    return events


def authorize_terminal_wait(
    runtime_path: Path,
    *,
    run_id: str,
    timeout_ms: int,
    source: str,
    event_id: str,
    occurred_at: str,
    adapter: dict[str, Any],
    event_schema: dict[str, Any],
    write: bool,
    host_tools: list[str] | dict | None = None,
) -> dict[str, Any]:
    runtime = load_structured_file(runtime_path)
    run = find_active_run(runtime, run_id)
    if adapter.get("provider") != run.get("provider"):
        raise TerminalWaitAuthorizationError("wait Adapter differs from Run provider")
    internal = run.get("provider") == "codex-subagent"
    budget = validate_wait_budget(run, timeout_ms, source)
    if internal:
        if (runtime.get("resolution") or {}).get("monitor_mode") != "milestone" or runtime.get("heartbeat"):
            raise TerminalWaitAuthorizationError("native agent wait requires milestone monitoring without Heartbeat")
    else:
        validate_heartbeat(runtime, run_id)
    inputs = {"worker_id": str(run["worker_id"]), "timeout_ms": timeout_ms}
    if run.get("event_cursor") and not internal:
        inputs["event_cursor"] = run["event_cursor"]
    # Validate the native timeout before consuming the durable budget.
    envelope = build_invocation(adapter, "wait", inputs, source=source, host_tools=host_tools)
    occurred = parse_time(occurred_at)
    enforced_at = parse_time(budget.get("enforced_at"))
    if occurred < enforced_at:
        raise TerminalWaitAuthorizationError("authorization predates wait_budget.enforced_at")

    active_attempts = [
        attempt
        for attempt in run.get("attempts", [])
        if attempt.get("status") in ACTIVE_STATUSES
    ]
    if len(active_attempts) != 1:
        raise TerminalWaitAuthorizationError("terminal wait requires one active Attempt")
    worker_id = str(run["worker_id"])
    event_cursor = run.get("event_cursor")
    event = {
        "schema_version": "1",
        "event_id": event_id,
        "event_type": "terminal-wait-authorized",
        "task_id": runtime.get("task_id"),
        "occurred_at": occurred_at,
        "run_id": run_id,
        "attempt_id": active_attempts[0].get("attempt_id"),
        "provider": run["provider"],
        "worker_id": worker_id,
        "payload": {
            "source": source,
            "timeout_ms": timeout_ms,
            "event_cursor": event_cursor,
        },
    }
    event_errors = validate_schema(event, event_schema, "event", event_schema)
    if event_errors:
        raise TerminalWaitAuthorizationError("; ".join(event_errors))

    path = event_log_path(runtime_path, runtime)
    if not path.exists():
        raise TerminalWaitAuthorizationError(f"event log does not exist: {path}")
    mode = "r+" if write else "r"
    with path.open(mode, encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        events = parse_events(stream, event_schema, path)
        if any(existing.get("event_id") == event_id for existing in events):
            raise TerminalWaitAuthorizationError(f"duplicate event_id {event_id!r}")
        if events and occurred < parse_time(events[-1].get("occurred_at")):
            raise TerminalWaitAuthorizationError("authorization is earlier than the event log tail")
        used = sum(
            1
            for existing in events
            if existing.get("event_type") == "terminal-wait-authorized"
            and existing.get("run_id") == run_id
            and parse_time(existing.get("occurred_at")) >= enforced_at
        )
        if used >= int(budget["max_calls"]):
            raise TerminalWaitAuthorizationError(
                f"Run {run_id} already consumed its terminal wait budget"
            )
        snapshots = [
            existing
            for existing in events
            if existing.get("event_type") == "status-observed"
            and existing.get("run_id") == run_id
            and existing.get("worker_id") == worker_id
            and parse_time(existing.get("occurred_at")) >= enforced_at
            and parse_time(existing.get("occurred_at")) <= occurred
            and (existing.get("payload") or {}).get("operation") == "inspect"
            and (existing.get("payload") or {}).get("timeout_ms") == 0
            and (existing.get("payload") or {}).get("source") == "coordinator"
        ]
        if not snapshots and not internal:
            raise TerminalWaitAuthorizationError(
                "terminal wait requires a recorded coordinator zero-wait snapshot"
            )
        if write:
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    native_target: dict[str, Any] = {"threadId": worker_id}
    if event_cursor:
        native_target["afterCursor"] = event_cursor
    return {
        "authorization": event,
        "adapter_envelope": envelope,
        "native_arguments": envelope.get("native_arguments") or {
            "targets": [native_target],
            "timeoutMs": timeout_ms,
        },
        "written": write,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Authorize the only positive terminal wait allowed for one Codex Run."
    )
    parser.add_argument("document", help="Task v4 or Runtime v1 path")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-ms", type=int, default=CODEX_WAIT_MAX_TIMEOUT_MS)
    parser.add_argument("--source", choices=["coordinator", "heartbeat"], default="coordinator")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--now", help="Authorization time; defaults to current UTC")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--host-tools", help="Live tool inventory with verified native bindings")
    args = parser.parse_args()

    runtime_path = resolve_runtime_path(Path(args.document).resolve())
    root = SCRIPT_DIR.parent
    runtime = load_structured_file(runtime_path)
    run = find_active_run(runtime, args.run_id)
    provider = run.get("provider")
    if provider not in {"codex", "codex-subagent"}:
        raise TerminalWaitAuthorizationError("unsupported wait provider")
    adapter = load_structured_file(root / "references" / "adapters" / f"{provider}.adapter.json")
    event_schema = load_structured_file(root / "references" / "schemas" / "runtime-event.schema.json")
    assert_supported_schema(event_schema, "runtime-event.schema.json")
    occurred_at = args.now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = authorize_terminal_wait(
        runtime_path,
        run_id=args.run_id,
        timeout_ms=args.timeout_ms,
        source=args.source,
        event_id=args.event_id,
        occurred_at=occurred_at,
        adapter=adapter,
        event_schema=event_schema,
        write=args.write,
        host_tools=json.loads(Path(args.host_tools).read_text()) if args.host_tools else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TerminalWaitAuthorizationError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

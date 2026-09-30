#!/usr/bin/env python3
"""Begin, complete, or roll back a bounded Worker provisioning transaction."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from monitor_policy import (  # noqa: E402
    PROVISIONING_DEFAULT_TTL_SECONDS,
    PROVISIONING_MAX_TTL_SECONDS,
    new_inspection_budget,
)
from record_runtime_event import append_event, resolve_runtime_path  # noqa: E402
from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_structured_file,
    parse_time,
    validate_schema,
)
from wait_policy import new_wait_budget  # noqa: E402


class DispatchTransactionError(ValueError):
    """Raised when Worker provisioning cannot transition atomically."""


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def find_run(runtime: dict[str, Any], run_id: str) -> dict[str, Any]:
    run = next(
        (item for item in runtime.get("runs", []) if item.get("run_id") == run_id),
        None,
    )
    if not isinstance(run, dict):
        raise DispatchTransactionError(f"unknown run_id {run_id!r}")
    return run


def current_attempt(run: dict[str, Any]) -> dict[str, Any]:
    attempts = [item for item in run.get("attempts", []) if isinstance(item, dict)]
    active = [
        item
        for item in attempts
        if item.get("status") in {"provisioning", "queued", "running"}
    ]
    if len(active) != 1:
        raise DispatchTransactionError("Run requires exactly one current Attempt")
    return active[0]


def require_active_heartbeat(runtime: dict[str, Any], run_id: str) -> None:
    resolution = runtime.get("resolution") or {}
    if resolution.get("provider") == "codex-subagent":
        if resolution.get("monitor_mode") != "milestone" or runtime.get("heartbeat"):
            raise DispatchTransactionError("native agents require milestone monitoring without Heartbeat")
        return
    heartbeat = runtime.get("heartbeat")
    if not isinstance(heartbeat, dict) or heartbeat.get("status") != "active":
        raise DispatchTransactionError("provisioning requires an active coordinator Heartbeat")
    if heartbeat.get("target_run_id") != run_id:
        raise DispatchTransactionError("Heartbeat must target the provisioning Run")
    if not heartbeat.get("coordinator_thread_id"):
        raise DispatchTransactionError("Heartbeat requires coordinator_thread_id")


def begin(
    runtime: dict[str, Any],
    run: dict[str, Any],
    *,
    transaction_id: str,
    now: datetime,
    ttl_seconds: int,
) -> tuple[dict[str, Any], str]:
    require_active_heartbeat(runtime, str(run.get("run_id") or ""))
    if run.get("worker_id"):
        raise DispatchTransactionError("cannot provision a Run that already has worker_id")
    if run.get("status") not in {"provisioning", "queued"}:
        raise DispatchTransactionError("begin requires a queued or provisioning Run")
    attempt = current_attempt(run)
    if attempt.get("lease") is not None:
        raise DispatchTransactionError("provisioning Attempt cannot already own a Lease")
    existing = run.get("provisioning")
    if isinstance(existing, dict) and existing.get("status") == "pending":
        if existing.get("transaction_id") == transaction_id:
            return attempt, "unchanged"
        raise DispatchTransactionError("Run already has a different pending transaction")
    deadline = now + timedelta(seconds=ttl_seconds)
    run["status"] = "provisioning"
    run["last_operation"] = "provision"
    run["last_idempotency_key"] = transaction_id
    run["provisioning"] = {
        "transaction_id": transaction_id,
        "status": "pending",
        "started_at": iso(now),
        "deadline_at": iso(deadline),
        "finished_at": None,
        "failure": None,
    }
    attempt["status"] = "provisioning"
    attempt["started_at"] = attempt.get("started_at") or iso(now)
    attempt["finished_at"] = None
    attempt["lease"] = None
    if run.get("provider") in {"codex", "codex-subagent"}:
        run.setdefault("wait_budget", new_wait_budget(iso(now)))
    if run.get("provider") == "codex":
        run.setdefault("inspection_budget", new_inspection_budget(iso(now)))
    for lock in runtime.get("resources", {}).get("locks", []):
        if lock.get("status") == "active" and lock.get("holder_run_id") == run.get("run_id"):
            lock["lease_expires_at"] = iso(deadline)
    return attempt, "changed"


def complete(
    runtime: dict[str, Any],
    run: dict[str, Any],
    *,
    transaction_id: str,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
) -> tuple[dict[str, Any], str]:
    transaction = run.get("provisioning")
    if (
        isinstance(transaction, dict)
        and transaction.get("status") == "completed"
        and transaction.get("transaction_id") == transaction_id
        and run.get("worker_id") == worker_id
    ):
        return current_attempt(run), "unchanged"
    if not isinstance(transaction, dict) or transaction.get("status") != "pending":
        raise DispatchTransactionError("complete requires pending provisioning")
    if transaction.get("transaction_id") != transaction_id:
        raise DispatchTransactionError("transaction_id does not match pending provisioning")
    require_active_heartbeat(runtime, str(run.get("run_id") or ""))
    if now >= parse_time(transaction.get("deadline_at")):
        raise DispatchTransactionError("provisioning deadline expired; roll back")
    attempt = current_attempt(run)
    expires = now + timedelta(seconds=lease_seconds)
    run["worker_id"] = worker_id
    run["status"] = "running"
    run["last_operation"] = "create"
    run["last_idempotency_key"] = transaction_id
    transaction.update(
        {"status": "completed", "finished_at": iso(now), "failure": None}
    )
    attempt["status"] = "running"
    attempt["started_at"] = attempt.get("started_at") or iso(now)
    attempt["finished_at"] = None
    attempt["lease"] = {
        "holder": run["run_id"],
        "acquired_at": iso(now),
        "heartbeat_at": iso(now),
        "expires_at": iso(expires),
        "renew_count": 0,
        "progress_seq": 0,
        "last_progress_at": iso(now),
        "last_progress_summary": "Worker created",
        "event_cursor": None,
        "liveness_state": "live",
        "monitor_gap_started_at": None,
        "disconnect_probe_count": 0,
        "disconnect_first_seen_at": None,
    }
    for lock in runtime.get("resources", {}).get("locks", []):
        if lock.get("status") == "active" and lock.get("holder_run_id") == run.get("run_id"):
            lock["lease_expires_at"] = iso(expires)
    return attempt, "changed"


def rollback(
    runtime: dict[str, Any],
    run: dict[str, Any],
    *,
    transaction_id: str,
    failure: str,
    now: datetime,
    heartbeat_stopped: bool,
) -> tuple[dict[str, Any], str]:
    transaction = run.get("provisioning")
    if (
        isinstance(transaction, dict)
        and transaction.get("status") == "rolled-back"
        and transaction.get("transaction_id") == transaction_id
    ):
        attempts = [item for item in run.get("attempts", []) if isinstance(item, dict)]
        return attempts[-1], "unchanged"
    if not heartbeat_stopped and (runtime.get("resolution") or {}).get("provider") != "codex-subagent":
        raise DispatchTransactionError(
            "pause or stop the external Heartbeat, then pass --heartbeat-stopped"
        )
    if not isinstance(transaction, dict) or transaction.get("status") != "pending":
        raise DispatchTransactionError("rollback requires pending provisioning")
    if transaction.get("transaction_id") != transaction_id:
        raise DispatchTransactionError("transaction_id does not match pending provisioning")
    attempt = current_attempt(run)
    run["status"] = "cancelled"
    run["finished_at"] = iso(now)
    run["last_operation"] = "rollback"
    run["last_idempotency_key"] = transaction_id
    transaction.update(
        {"status": "rolled-back", "finished_at": iso(now), "failure": failure}
    )
    attempt["status"] = "cancelled"
    attempt["finished_at"] = iso(now)
    attempt["lease"] = None
    for lock in runtime.get("resources", {}).get("locks", []):
        if lock.get("status") == "active" and lock.get("holder_run_id") == run.get("run_id"):
            lock["status"] = "released"
            lock["lease_expires_at"] = iso(now)
    heartbeat = runtime.get("heartbeat")
    if isinstance(heartbeat, dict) and heartbeat.get("target_run_id") == run.get("run_id"):
        heartbeat["status"] = "stopped"
    return attempt, "changed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage one Worker provisioning transaction.")
    parser.add_argument("document")
    parser.add_argument("operation", choices=["begin", "complete", "rollback"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--worker-id")
    parser.add_argument("--failure")
    parser.add_argument("--ttl-seconds", type=int, default=PROVISIONING_DEFAULT_TTL_SECONDS)
    parser.add_argument("--lease-seconds", type=int, default=3600)
    parser.add_argument("--heartbeat-stopped", action="store_true")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--now")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.ttl_seconds <= PROVISIONING_MAX_TTL_SECONDS:
        parser.error(f"--ttl-seconds must be within 1..{PROVISIONING_MAX_TTL_SECONDS}")
    if args.lease_seconds < 60:
        parser.error("--lease-seconds must be at least 60")
    if args.operation == "complete" and not args.worker_id:
        parser.error("--worker-id is required for complete")
    if args.operation == "rollback" and not args.failure:
        parser.error("--failure is required for rollback")

    runtime_path = resolve_runtime_path(Path(args.document).resolve())
    schema_dir = SCRIPT_DIR.parent / "references" / "schemas"
    runtime_schema = load_structured_file(schema_dir / "runtime.schema.json")
    event_schema = load_structured_file(schema_dir / "runtime-event.schema.json")
    assert_supported_schema(runtime_schema, "runtime.schema.json")
    assert_supported_schema(event_schema, "runtime-event.schema.json")
    occurred_at = args.now or iso(datetime.now(timezone.utc))
    now = parse_time(occurred_at)
    lock_path = runtime_path.with_name(runtime_path.name + ".dispatch.lock")
    lock_target = lock_path if args.write else runtime_path
    if args.write:
        lock_path.touch(exist_ok=True)
    with lock_target.open("r+" if args.write else "r", encoding="utf-8") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX if args.write else fcntl.LOCK_SH)
        runtime = load_structured_file(runtime_path)
        run = find_run(runtime, args.run_id)
        if args.operation == "begin":
            attempt, change = begin(
                runtime,
                run,
                transaction_id=args.transaction_id,
                now=now,
                ttl_seconds=args.ttl_seconds,
            )
            event_type = "dispatch-provisioning-started"
        elif args.operation == "complete":
            attempt, change = complete(
                runtime,
                run,
                transaction_id=args.transaction_id,
                worker_id=str(args.worker_id),
                now=now,
                lease_seconds=args.lease_seconds,
            )
            event_type = "dispatch-provisioning-completed"
        else:
            attempt, change = rollback(
                runtime,
                run,
                transaction_id=args.transaction_id,
                failure=str(args.failure),
                now=now,
                heartbeat_stopped=args.heartbeat_stopped,
            )
            event_type = "dispatch-provisioning-rolled-back"
        runtime["last_updated"] = occurred_at
        errors = validate_schema(runtime, runtime_schema, str(runtime_path), runtime_schema)
        if errors:
            raise DispatchTransactionError("; ".join(errors))
        event = {
            "schema_version": "1",
            "event_id": args.event_id,
            "event_type": event_type,
            "task_id": runtime.get("task_id"),
            "occurred_at": occurred_at,
            "run_id": run.get("run_id"),
            "attempt_id": attempt.get("attempt_id"),
            "provider": run.get("provider"),
            "worker_id": run.get("worker_id"),
            "payload": {
                "transaction_id": args.transaction_id,
                "change": change,
                "failure": args.failure,
            },
        }
        if args.write and change == "changed":
            atomic_write(runtime_path, runtime)
            append_event(runtime_path, event, event_schema, True)
    print(
        json.dumps(
            {"operation": args.operation, "change": change, "run": run, "event": event, "written": args.write},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, DispatchTransactionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

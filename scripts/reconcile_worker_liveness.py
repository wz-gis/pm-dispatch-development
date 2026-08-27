#!/usr/bin/env python3
"""Apply one metadata-only Worker liveness probe to a Runtime Run."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_pm_dispatch import (  # noqa: E402
    load_structured_file,
    parse_time,
    runtime_file_for,
)


ACTIVE = {"queued", "running"}
TERMINAL = {"succeeded", "failed", "blocked", "cancelled"}


class LivenessError(ValueError):
    """Raised when a probe cannot be reconciled without guessing."""


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def reconcile_liveness(
    source: dict[str, Any],
    run_id: str,
    probe_status: str,
    now: datetime,
    lease_minutes: int = 30,
    grace_seconds: int = 60,
) -> tuple[dict[str, Any], str]:
    task = copy.deepcopy(source)
    run = next((item for item in task.get("runs", []) if item.get("run_id") == run_id), None)
    if not run:
        raise LivenessError(f"unknown run_id {run_id!r}")
    if run.get("status") not in ACTIVE:
        raise LivenessError(f"run {run_id!r} is not active")

    attempts = [item for item in run.get("attempts", []) if item.get("status") in ACTIVE]
    if len(attempts) != 1:
        raise LivenessError(f"run {run_id!r} requires exactly one active Attempt")
    attempt = attempts[0]
    lease = attempt.get("lease")
    if not isinstance(lease, dict):
        raise LivenessError(f"run {run_id!r} has no Lease")

    now_text = isoformat(now)
    if probe_status == "running":
        lease["heartbeat_at"] = now_text
        lease["expires_at"] = isoformat(now + timedelta(minutes=lease_minutes))
        lease["renew_count"] = int(lease.get("renew_count") or 0) + 1
        lease["liveness_state"] = "live"
        lease["monitor_gap_started_at"] = None
        lease["disconnect_probe_count"] = 0
        lease["disconnect_first_seen_at"] = None
        sync_active_locks(task, run_id, lease["expires_at"])
        outcome = "renewed-same-attempt"
    elif probe_status in TERMINAL:
        run["status"] = probe_status
        run["finished_at"] = now_text
        attempt["status"] = probe_status
        attempt["finished_at"] = now_text
        lease["liveness_state"] = "live"
        lease["monitor_gap_started_at"] = None
        release_locks(task, run_id, now_text)
        outcome = f"terminal-{probe_status}"
    elif probe_status == "monitor-unavailable":
        lease["liveness_state"] = "unknown"
        lease["monitor_gap_started_at"] = lease.get("monitor_gap_started_at") or now_text
        outcome = "ownership-held-monitor-gap"
    elif probe_status == "unreachable":
        lease["liveness_state"] = "unknown"
        lease["monitor_gap_started_at"] = lease.get("monitor_gap_started_at") or now_text
        count = int(lease.get("disconnect_probe_count") or 0)
        first_seen = lease.get("disconnect_first_seen_at")
        if count == 0 or not first_seen:
            lease["disconnect_probe_count"] = 1
            lease["disconnect_first_seen_at"] = now_text
            lease["expires_at"] = isoformat(now + timedelta(seconds=grace_seconds))
            sync_active_locks(task, run_id, lease["expires_at"])
            outcome = "grace-probe-required"
        elif now < parse_time(first_seen) + timedelta(seconds=grace_seconds):
            raise LivenessError("disconnect grace period has not elapsed")
        else:
            lease["disconnect_probe_count"] = count + 1
            run["status"] = "expired"
            run["finished_at"] = now_text
            attempt["status"] = "expired"
            attempt["finished_at"] = now_text
            release_locks(task, run_id, now_text)
            outcome = "expired-replacement-allowed"
    else:
        raise LivenessError(f"unsupported probe_status {probe_status!r}")

    task["last_updated"] = now_text
    return task, outcome


def release_locks(task: dict[str, Any], run_id: str, released_at: str) -> None:
    for lock in task.get("resources", {}).get("locks", []):
        if lock.get("holder_run_id") == run_id and lock.get("status") == "active":
            lock["status"] = "released"
            lock["lease_expires_at"] = released_at


def sync_active_locks(task: dict[str, Any], run_id: str, expires_at: str) -> None:
    for lock in task.get("resources", {}).get("locks", []):
        if lock.get("holder_run_id") == run_id and lock.get("status") == "active":
            lock["lease_expires_at"] = expires_at


def atomic_write(path: Path, task: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.liveness")
    temporary.write_text(
        json.dumps(task, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile one Worker liveness probe.")
    parser.add_argument("document", help="Path to Task v3, Task v4, or runtime.yaml")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--probe-status",
        required=True,
        choices=[
            "running",
            "succeeded",
            "failed",
            "blocked",
            "cancelled",
            "monitor-unavailable",
            "unreachable",
        ],
    )
    parser.add_argument("--now", help="Probe time in ISO-8601; defaults to current UTC")
    parser.add_argument("--lease-minutes", type=int, default=30)
    parser.add_argument("--grace-seconds", type=int, default=60)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.lease_minutes < 1 or args.grace_seconds < 1:
        raise LivenessError("lease-minutes and grace-seconds must be positive")

    input_path = Path(args.document).resolve()
    source = load_structured_file(input_path)
    path = input_path
    if source.get("schema_version") == "4" and "dispatch" in source:
        runtime_path = runtime_file_for(input_path, source, None)
        if runtime_path is None or not runtime_path.exists():
            raise LivenessError("Task v4 Runtime sidecar is missing")
        path = runtime_path
        source = load_structured_file(runtime_path)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    task, outcome = reconcile_liveness(
        source,
        args.run_id,
        args.probe_status,
        now,
        args.lease_minutes,
        args.grace_seconds,
    )
    if args.write:
        atomic_write(path, task)
    print(json.dumps({"outcome": outcome, "task": task}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, LivenessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

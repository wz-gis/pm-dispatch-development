#!/usr/bin/env python3
"""Apply one metadata-only Worker liveness probe to a Runtime Run."""

from __future__ import annotations

import argparse
import copy
import fcntl
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


def observe_progress(
    run: dict[str, Any], lease: dict[str, Any], probe_status: str, now: datetime,
    *, command_id: str | None, command_deadline: str | None, stale_after_seconds: int,
) -> str | None:
    previous = run.get("observation") or {}
    seq = int(lease.get("progress_seq") or 0)
    progress_at = (lease.get("last_progress_at") or run.get("started_at") or lease.get("acquired_at")
                   or previous.get("last_progress_at") or isoformat(now))
    previous_at = previous.get("last_progress_at")
    progressed = seq > int(previous.get("progress_seq") or 0) or bool(
        progress_at and previous_at and parse_time(progress_at) > parse_time(previous_at)
    )
    if previous.get("observed_at") and now < parse_time(previous["observed_at"]):
        raise LivenessError("probe is older than the last observation")
    if seq < int(previous.get("progress_seq") or 0):
        raise LivenessError("progress_seq must not move backwards")
    observation = {
        "provider_status": probe_status, "observed_at": isoformat(now),
        "progress_seq": seq, "last_progress_at": progress_at,
        "state": "active", "reason": None, "attention_at": None,
        "command_id": None, "command_deadline": None,
    }
    if not progressed:
        for key in ("state", "reason", "attention_at", "command_id", "command_deadline"):
            observation[key] = previous.get(key, observation[key])
    if bool(command_id) != bool(command_deadline):
        raise LivenessError("a verified running command requires both command-id and command-deadline")
    if command_id:
        deadline = parse_time(command_deadline)
        if not progressed and previous.get("command_id"):
            if command_id != previous["command_id"] or deadline != parse_time(previous["command_deadline"]):
                raise LivenessError("a command deadline cannot be extended without a new milestone")
        elif deadline <= now:
            raise LivenessError("new command deadline must be in the future")
        observation["command_id"] = command_id
        observation["command_deadline"] = isoformat(deadline)
        if observation["reason"] == "no-progress" and not previous.get("command_id") and deadline > now:
            observation.update(state="waiting-command", reason=None, attention_at=None)
    reason = None
    if probe_status in {"idle", "interrupted"}:
        reason = "interrupted" if probe_status == "interrupted" else "idle-without-outcome"
    elif observation["attention_at"]:
        reason = observation["reason"]
    elif observation["command_deadline"] and now < parse_time(observation["command_deadline"]):
        observation["state"] = "waiting-command"
    elif progress_at and (now - parse_time(progress_at)).total_seconds() >= stale_after_seconds:
        reason = "no-progress"
    else:
        observation["state"] = "active"
    outcome = None
    if reason:
        first = not observation["attention_at"]
        observation.update(state="attention", reason=reason,
                           attention_at=observation["attention_at"] or isoformat(now))
        outcome = "diagnosis-required" if first else "awaiting-diagnosis"
    run["observation"] = observation
    return outcome


def reconcile_liveness(
    source: dict[str, Any],
    run_id: str,
    probe_status: str,
    now: datetime,
    lease_minutes: int = 30,
    grace_seconds: int = 60,
    *,
    latest_turn_status: str | None = None,
    terminal_outcome: str | None = None,
    command_id: str | None = None,
    command_deadline: str | None = None,
    stale_after_seconds: int = 1800,
) -> tuple[dict[str, Any], str]:
    task = copy.deepcopy(source)
    run = next((item for item in task.get("runs", []) if item.get("run_id") == run_id), None)
    if not run:
        raise LivenessError(f"unknown run_id {run_id!r}")
    if run.get("status") not in ACTIVE:
        if run.get("status") in TERMINAL and probe_status in {run["status"], "idle"}:
            return task, "terminal-already-reconciled"
        raise LivenessError(f"run {run_id!r} is not active")
    if lease_minutes < 1 or grace_seconds < 1 or stale_after_seconds < 600:
        raise LivenessError("lease/grace must be positive; no-progress window must be at least one 600s tick")

    attempts = [item for item in run.get("attempts", []) if item.get("status") in ACTIVE]
    if len(attempts) != 1:
        raise LivenessError(f"run {run_id!r} requires exactly one active Attempt")
    attempt = attempts[0]
    lease = attempt.get("lease")
    if not isinstance(lease, dict):
        raise LivenessError(f"run {run_id!r} has no Lease")

    now_text = isoformat(now)
    if terminal_outcome and terminal_outcome not in TERMINAL:
        raise LivenessError(f"unsupported terminal_outcome {terminal_outcome!r}")
    if probe_status == "idle" and latest_turn_status == "completed":
        if not terminal_outcome:
            raise LivenessError(
                "idle Worker with a completed latest turn requires an explicit terminal outcome"
            )
        probe_status = terminal_outcome
    elif terminal_outcome:
        raise LivenessError(
            "terminal_outcome is only valid for an idle Worker with a completed latest turn"
        )
    if probe_status == "idle" and latest_turn_status == "interrupted":
        probe_status = "interrupted"
    if probe_status in {"running", "queued", "idle", "interrupted"}:
        # Idle is not a successful delegation, nor proof that subprocesses stopped.
        run["status"] = "running" if probe_status == "running" else "queued"
        attempt["status"] = run["status"]
        lease["heartbeat_at"] = now_text
        lease["expires_at"] = isoformat(now + timedelta(minutes=lease_minutes))
        lease["renew_count"] = int(lease.get("renew_count") or 0) + 1
        lease["liveness_state"] = "live"
        lease["monitor_gap_started_at"] = None
        lease["disconnect_probe_count"] = 0
        lease["disconnect_first_seen_at"] = None
        sync_active_locks(task, run_id, lease["expires_at"])
        outcome = observe_progress(
            run, lease, probe_status, now, command_id=command_id,
            command_deadline=command_deadline, stale_after_seconds=stale_after_seconds,
        ) or "renewed-same-attempt"
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
            "queued",
            "idle",
            "interrupted",
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
    parser.add_argument("--latest-turn-status", choices=["running", "completed", "failed", "interrupted"])
    parser.add_argument(
        "--terminal-outcome",
        choices=["succeeded", "failed", "blocked", "cancelled"],
        help="Required classification for idle + completed latest turn",
    )
    parser.add_argument("--command-id", help="ID of a verified running build/test process")
    parser.add_argument("--command-deadline", help="Fixed expected completion deadline; never slide it each tick")
    parser.add_argument("--stale-after-seconds", type=int, default=1800)
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
    # Lock a stable sidecar, not the inode replaced by atomic_write.
    with path.with_name(path.name + ".liveness.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if args.write else fcntl.LOCK_SH)
        source = load_structured_file(path)
        task, outcome = reconcile_liveness(
            source, args.run_id, args.probe_status, now, args.lease_minutes, args.grace_seconds,
            latest_turn_status=args.latest_turn_status, command_id=args.command_id,
            terminal_outcome=args.terminal_outcome, command_deadline=args.command_deadline,
            stale_after_seconds=args.stale_after_seconds,
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

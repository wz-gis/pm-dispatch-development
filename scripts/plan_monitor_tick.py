#!/usr/bin/env python3
"""Plan one model-free monitor tick from Runtime and immutable events."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from record_runtime_event import resolve_runtime_path  # noqa: E402
from monitor_policy import pending_inspection_authorizations  # noqa: E402
from validate_pm_dispatch import load_structured_file, parse_time  # noqa: E402


TERMINAL_STATUSES = {"succeeded", "failed", "blocked", "expired", "cancelled"}


def event_path(runtime_path: Path, runtime: dict[str, Any]) -> Path:
    configured_value = str(runtime.get("event_log_file") or "").strip()
    if not configured_value:
        raise ValueError("Runtime requires event_log_file")
    configured = Path(configured_value)
    return configured if configured.is_absolute() else (runtime_path.parent / configured).resolve()


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def plan_monitor_tick(
    runtime: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    heartbeat = runtime.get("heartbeat") or {}
    run_id = heartbeat.get("target_run_id")
    run = next(
        (item for item in runtime.get("runs", []) if item.get("run_id") == run_id),
        None,
    )
    if heartbeat.get("status") != "active":
        return {
            "action": "stop",
            "reason": "heartbeat-not-active",
            "run_id": run_id,
            "required_host_action": "none",
        }
    if not isinstance(run, dict):
        return {"action": "repair-runtime", "reason": "target-run-missing", "run_id": run_id}
    status = run.get("status")
    if status in TERMINAL_STATUSES:
        if any(event.get("event_type") == "terminal-collected"
               and event.get("run_id") == run_id
               and parse_time(event.get("occurred_at")) >= parse_time(run.get("finished_at"))
               for event in events):
            return {
                "action": "stop",
                "reason": "terminal-already-collected",
                "run_id": run_id,
                "required_host_action": "pause-heartbeat",
            }
        return {
            "action": "collect-terminal",
            "reason": "run-terminal",
            "run_id": run_id,
            "required_host_action": "collect-once-then-pause-heartbeat",
        }
    if status == "provisioning":
        deadline = parse_time((run.get("provisioning") or {}).get("deadline_at"))
        if now >= deadline:
            return {
                "action": "rollback-provisioning",
                "reason": "provisioning-deadline-expired",
                "run_id": run_id,
                "required_host_action": "rollback-provisioning-then-pause-heartbeat",
            }
        return {
            "action": "sleep",
            "reason": "worker-create-in-progress",
            "run_id": run_id,
            "next_check_at": deadline.isoformat().replace("+00:00", "Z"),
        }
    if status not in {"queued", "running"} or not run.get("worker_id"):
        return {"action": "repair-runtime", "reason": "run-not-executable", "run_id": run_id}
    budget = run.get("inspection_budget") or {}
    interval = int(budget.get("min_interval_seconds") or 600)
    enforced_at = parse_time(budget.get("enforced_at"))
    pending = [
        event
        for event in pending_inspection_authorizations(events, str(run_id))
        if parse_time(event.get("occurred_at")) >= enforced_at
    ]
    if pending:
        latest = max(pending, key=lambda event: parse_time(event.get("occurred_at")))
        return {
            "action": "reconcile-pending-inspection",
            "reason": "status-observation-missing",
            "run_id": run_id,
            "authorization_event_id": latest.get("event_id"),
            "required_host_action": "recover-result-once-or-pause-heartbeat",
            "resume_allowed": False,
        }
    prior = [
        event
        for event in events
        if event.get("event_type") == "status-inspect-authorized"
        and event.get("run_id") == run_id
        and parse_time(event.get("occurred_at")) >= enforced_at
    ]
    if prior:
        latest = max(parse_time(event.get("occurred_at")) for event in prior)
        next_check = latest + timedelta(seconds=interval)
        if now < next_check:
            return {
                "action": "sleep",
                "reason": "inspection-debounced",
                "run_id": run_id,
                "next_check_at": next_check.isoformat().replace("+00:00", "Z"),
            }
    return {
        "action": "inspect",
        "reason": "scheduled",
        "run_id": run_id,
        "worker_id": run.get("worker_id"),
        "timeout_ms": 0,
        "follow_up": "reconcile-once",
        "resume_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan one deterministic PM monitor tick.")
    parser.add_argument("document")
    parser.add_argument("--now")
    args = parser.parse_args()
    runtime_path = resolve_runtime_path(Path(args.document).resolve())
    runtime = load_structured_file(runtime_path)
    now = parse_time(
        args.now
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    result = plan_monitor_tick(runtime, load_events(event_path(runtime_path, runtime)), now=now)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

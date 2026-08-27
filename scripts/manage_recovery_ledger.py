#!/usr/bin/env python3
"""Record recovery paths and enforce a Gate-level circuit breaker."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_structured_file,
    validate_schema,
)


GATES = ["contract", "implementation", "integration", "verification", "closure"]


def utc_now(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def default_path(task_path: Path) -> Path:
    return task_path.resolve().parent / "context" / "recovery-ledger.json"


def load_task(task_path: Path, schema_dir: Path) -> dict[str, Any]:
    schema = load_structured_file(schema_dir / "task.schema.json")
    assert_supported_schema(schema, "task.schema.json")
    task = load_structured_file(task_path)
    errors = validate_schema(task, schema, str(task_path), schema)
    if errors:
        raise ValueError("invalid Task:\n" + "\n".join(errors))
    return task


def initial_ledger(task_id: str, now: str) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "task_id": task_id,
        "policy": {"max_same_method_failures": 2, "max_failed_paths": 3},
        "gates": [],
        "last_updated": now,
    }


def validate_ledger(
    ledger: dict[str, Any], path: Path, schema_dir: Path
) -> list[str]:
    schema = load_structured_file(schema_dir / "recovery-ledger.schema.json")
    assert_supported_schema(schema, "recovery-ledger.schema.json")
    errors = validate_schema(ledger, schema, str(path), schema)
    gates = [item.get("gate") for item in ledger.get("gates", []) if isinstance(item, dict)]
    if len(gates) != len(set(gates)):
        errors.append(f"{path}: duplicate Gate entries are not allowed")
    for gate in ledger.get("gates", []):
        attempts = gate.get("attempts", [])
        keys = [item.get("attempt_key") for item in attempts]
        if len(keys) != len(set(keys)):
            errors.append(f"{path}: duplicate recovery attempt_key in {gate.get('gate')}")
        failure = gate.get("failure")
        if gate.get("breaker", {}).get("state") == "open" and not failure:
            errors.append(f"{path}: open breaker requires current failure")
    return errors


def gate_entry(
    ledger: dict[str, Any], gate: str, design_fingerprint: str | None
) -> dict[str, Any]:
    for item in ledger["gates"]:
        if item["gate"] == gate:
            return item
    item = {
        "gate": gate,
        "design_fingerprint": design_fingerprint,
        "failure": None,
        "attempts": [],
        "breaker": {
            "state": "closed",
            "reason": None,
            "opened_at": None,
            "reset_at": None,
            "reset_reason": None,
        },
    }
    ledger["gates"].append(item)
    return item


def failed_attempts_for(entry: dict[str, Any], fingerprint: str) -> list[dict[str, Any]]:
    return [
        item
        for item in entry["attempts"]
        if item["failure_fingerprint"] == fingerprint and item["result"] == "failed"
    ]


def breaker_summary(entry: dict[str, Any]) -> dict[str, Any]:
    failure = entry.get("failure") or {}
    fingerprint = failure.get("fingerprint")
    failed = failed_attempts_for(entry, fingerprint) if fingerprint else []
    methods = list(dict.fromkeys(item["method"] for item in failed))
    return {
        "gate": entry["gate"],
        "state": entry["breaker"]["state"],
        "failure_fingerprint": fingerprint,
        "failed_attempt_count": len(failed),
        "failed_paths": methods,
        "remaining_paths": max(0, 3 - len(methods)),
        "next_action": failure.get("next_action"),
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage a PM Gate recovery ledger.")
    parser.add_argument("task")
    parser.add_argument("operation", choices=["init", "record", "check", "reset", "validate"])
    parser.add_argument("--ledger")
    parser.add_argument("--gate", choices=GATES)
    parser.add_argument("--design-fingerprint")
    parser.add_argument("--failure-class")
    parser.add_argument("--failure-fingerprint")
    parser.add_argument("--diagnosis-status", choices=["unknown", "diagnosing", "confirmed", "resolved"], default="confirmed")
    parser.add_argument("--checkpoint-ref")
    parser.add_argument("--next-action")
    parser.add_argument("--attempt-key")
    parser.add_argument("--method")
    parser.add_argument("--result", choices=["failed", "recovered"])
    parser.add_argument("--artifact-ref", action="append", default=[])
    parser.add_argument("--reason")
    parser.add_argument("--now")
    args = parser.parse_args()

    task_path = Path(args.task).resolve()
    schema_dir = SCRIPT_DIR.parent / "references" / "schemas"
    task = load_task(task_path, schema_dir)
    path = Path(args.ledger).resolve() if args.ledger else default_path(task_path)
    now = utc_now(args.now)
    ledger = load_structured_file(path) if path.exists() else initial_ledger(task["id"], now)
    if ledger.get("task_id") != task["id"]:
        raise ValueError("Recovery Ledger task_id does not match Task")

    if args.operation == "validate":
        errors = validate_ledger(ledger, path, schema_dir)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("PM recovery ledger validation passed.")
        return 0

    if args.operation == "init":
        errors = validate_ledger(ledger, path, schema_dir)
        if errors:
            raise ValueError("invalid Recovery Ledger:\n" + "\n".join(errors))
        atomic_write(path, ledger)
        print(f"Wrote {path}")
        return 0

    if not args.gate:
        parser.error("--gate is required")
    design_fingerprint = args.design_fingerprint or (
        (task.get("dispatch", {}).get("design_freeze") or {}).get("fingerprint")
    )
    entry = gate_entry(ledger, args.gate, design_fingerprint)

    if args.operation == "check":
        summary = breaker_summary(entry)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2 if summary["state"] == "open" else 0

    if args.operation == "reset":
        if not args.reason:
            parser.error("--reason is required for reset")
        previous_fingerprint = entry.get("design_fingerprint")
        if design_fingerprint == previous_fingerprint and "contract" not in args.reason.lower() and "design" not in args.reason.lower():
            raise ValueError(
                "reset requires a changed design fingerprint or an explicit contract/design reason"
            )
        entry["design_fingerprint"] = design_fingerprint
        entry["failure"] = None
        entry["breaker"] = {
            "state": "closed",
            "reason": None,
            "opened_at": None,
            "reset_at": now,
            "reset_reason": args.reason,
        }
    elif args.operation == "record":
        required = {
            "--failure-class": args.failure_class,
            "--failure-fingerprint": args.failure_fingerprint,
            "--attempt-key": args.attempt_key,
            "--method": args.method,
            "--result": args.result,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error("required for record: " + ", ".join(missing))
        if entry["breaker"]["state"] == "open":
            raise ValueError("circuit breaker is open; repair the contract and reset first")
        fingerprint = str(args.failure_fingerprint)
        previous = failed_attempts_for(entry, fingerprint)
        same_method_failures = sum(1 for item in previous if item["method"] == args.method)
        if args.result == "failed" and same_method_failures >= ledger["policy"]["max_same_method_failures"]:
            raise ValueError("same recovery method already failed twice; choose a new path")
        entry["design_fingerprint"] = design_fingerprint
        entry["failure"] = {
            "failure_class": str(args.failure_class),
            "fingerprint": fingerprint,
            "diagnosis_status": "resolved" if args.result == "recovered" else args.diagnosis_status,
            "checkpoint_ref": args.checkpoint_ref,
            "next_action": args.next_action,
        }
        entry["attempts"].append(
            {
                "attempt_key": str(args.attempt_key),
                "failure_fingerprint": fingerprint,
                "method": str(args.method),
                "result": str(args.result),
                "artifact_refs": list(dict.fromkeys(args.artifact_ref)),
                "recorded_at": now,
            }
        )
        if args.result == "recovered":
            entry["breaker"]["state"] = "closed"
            entry["breaker"]["reason"] = None
            entry["breaker"]["opened_at"] = None
        else:
            failed = failed_attempts_for(entry, fingerprint)
            failed_paths = set(item["method"] for item in failed)
            if len(failed_paths) >= ledger["policy"]["max_failed_paths"]:
                entry["breaker"] = {
                    "state": "open",
                    "reason": "same Gate and failure fingerprint exhausted three recovery paths",
                    "opened_at": now,
                    "reset_at": entry["breaker"].get("reset_at"),
                    "reset_reason": entry["breaker"].get("reset_reason"),
                }
    ledger["last_updated"] = now
    errors = validate_ledger(ledger, path, schema_dir)
    if errors:
        raise ValueError("invalid Recovery Ledger:\n" + "\n".join(errors))
    atomic_write(path, ledger)
    print(json.dumps(breaker_summary(entry), ensure_ascii=False, sort_keys=True))
    return 2 if entry["breaker"]["state"] == "open" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

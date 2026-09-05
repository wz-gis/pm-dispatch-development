#!/usr/bin/env python3
"""Record recovery paths and enforce a Gate-level circuit breaker."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    design_freeze_fingerprint,
    load_structured_file,
    validate_schema,
)
from context_source_digest import file_sha256  # noqa: E402


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
    if errors:
        return errors
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
        pending = [item for item in attempts if item["result"] == "pending"]
        if len(pending) > 1:
            errors.append(f"{path}: only one pending recovery is allowed per Gate")
        if pending and (not unresolved(gate) or pending[0]["failure_fingerprint"] != failure["fingerprint"]):
            errors.append(f"{path}: pending recovery must match the unresolved failure")
        if failure:
            matching = [item for item in attempts if item["failure_fingerprint"] == failure["fingerprint"]]
            if not matching or (failure["diagnosis_status"] == "resolved") != (matching[-1]["result"] == "recovered"):
                errors.append(f"{path}: failure diagnosis must agree with its recorded recovery outcome")
        resets = gate.get("resets", [])
        offsets = [item["after_attempt"] for item in resets]
        if offsets != sorted(set(offsets)) or any(offset > len(attempts) for offset in offsets):
            errors.append(f"{path}: invalid recovery reset boundary")
        for reset in resets:
            if reset["before_sha256"] == reset["after_sha256"]:
                errors.append(f"{path}: reset proof must demonstrate a change")
        if unresolved(gate):
            failed = failed_attempts_for(gate, failure["fingerprint"])
            methods = {item["method"] for item in failed}
            if len(methods) >= ledger["policy"]["max_failed_paths"] and gate["breaker"]["state"] != "open":
                errors.append(f"{path}: exhausted recovery paths require an open breaker")
            if any(sum(item["method"] == method for item in failed) > ledger["policy"]["max_same_method_failures"] for method in methods):
                errors.append(f"{path}: recovery method budget exceeded")
            if pending and sum(item["method"] == pending[0]["method"] for item in failed) >= ledger["policy"]["max_same_method_failures"]:
                errors.append(f"{path}: pending recovery exceeds the same-method budget")
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
    resets = entry.get("resets", [])
    start = resets[-1]["after_attempt"] if resets else 0
    return [
        item
        for item in entry["attempts"][start:]
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


def unresolved(entry: dict[str, Any]) -> bool:
    failure = entry.get("failure")
    return bool(failure and failure.get("diagnosis_status") != "resolved")


def execution_error(
    ledger: dict[str, Any], gate: str | None, attempt_key: str | None = None
) -> str | None:
    entries = [item for item in ledger["gates"] if unresolved(item)]
    # A different Gate is not an escape hatch for an unresolved failure.
    for entry in entries:
        if entry["breaker"]["state"] == "open":
            return f"{entry['gate']}: circuit breaker is open; inspect or repair the contract before execution"
        if entry["gate"] != gate:
            return f"{entry['gate']}: unresolved recovery must be reconciled before changing Gate"
        if not any(item["attempt_key"] == attempt_key and item["result"] == "pending" for item in entry["attempts"]):
            return f"{gate}: unresolved failure requires authorize and --recovery-attempt before execution"
    if attempt_key and not entries:
        return "recovery attempt is no longer pending; rebuild the continuation packet"
    return None


@contextmanager
def ledger_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def ensure_ledger(task_path: Path, task_id: str, now: str, schema_dir: Path) -> Path:
    path = default_path(task_path)
    with ledger_lock(path):
        ledger = load_structured_file(path) if path.exists() else initial_ledger(task_id, now)
        errors = validate_ledger(ledger, path, schema_dir)
        if ledger.get("task_id") != task_id:
            errors.append("Recovery Ledger task_id does not match Task")
        if errors:
            raise ValueError("invalid Recovery Ledger:\n" + "\n".join(errors))
        if not path.exists():
            atomic_write(path, ledger)
    return path


def artifact_path(task_path: Path, ref: str) -> Path:
    path = Path(ref)
    return path.resolve() if path.is_absolute() else (task_path.parent / path).resolve()


def mutate(args: argparse.Namespace, task_path: Path, task: dict, path: Path, schema_dir: Path) -> int:
    now = utc_now(args.now)
    ledger = load_structured_file(path) if path.exists() else initial_ledger(task["id"], now)
    if ledger.get("task_id") != task["id"]:
        raise ValueError("Recovery Ledger task_id does not match Task")
    errors = validate_ledger(ledger, path, schema_dir)
    if errors:
        raise ValueError("invalid Recovery Ledger:\n" + "\n".join(errors))
    if args.operation == "import":
        if not args.import_ledger:
            raise ValueError("import requires --import-ledger")
        imported = load_structured_file(Path(args.import_ledger).resolve())
        errors = validate_ledger(imported, Path(args.import_ledger), schema_dir)
        if imported.get("task_id") != task["id"]:
            errors.append("imported Recovery Ledger task_id does not match Task")
        if ledger["gates"]:
            errors.append("canonical ledger is not empty; reconcile histories explicitly, never overwrite")
        if errors:
            raise ValueError("invalid ledger import:\n" + "\n".join(errors))
        atomic_write(path, imported)
        print(f"Imported {path}")
        return 0
    if args.operation in {"init", "validate"}:
        if args.operation == "init":
            atomic_write(path, ledger)
        print(f"Recovery Ledger {args.operation}: {path}")
        return 0
    if not args.gate:
        raise ValueError("--gate is required")
    freeze = task.get("dispatch", {}).get("design_freeze") or {}
    design_fingerprint = design_freeze_fingerprint(freeze) if freeze else None
    if args.design_fingerprint and args.design_fingerprint != design_fingerprint:
        raise ValueError("--design-fingerprint must match the actual Task design freeze")
    entry = gate_entry(ledger, args.gate, design_fingerprint)
    if args.operation == "check":
        print(json.dumps(breaker_summary(entry), ensure_ascii=False, sort_keys=True))
        return 2 if entry["breaker"]["state"] == "open" else 0
    if args.operation == "reset":
        if not args.reason or not args.artifact_ref:
            raise ValueError("reset requires --reason and --artifact-ref evidence")
        if not unresolved(entry) or any(item["result"] == "pending" for item in entry["attempts"]):
            raise ValueError("reset requires an unresolved failure with no pending recovery")
        proofs = []
        for ref in args.artifact_ref:
            artifact = artifact_path(task_path, ref)
            if not artifact.is_file():
                raise ValueError(f"reset evidence is missing: {artifact}")
            proofs.append({"path": str(artifact), "sha256": file_sha256(artifact)})
        before = entry.get("design_fingerprint")
        after = design_fingerprint
        kind = "design"
        if not before or not after or before == after:
            failure = entry["failure"]
            ref = failure.get("checkpoint_ref")
            checkpoint = artifact_path(task_path, ref) if ref else None
            before = failure.get("checkpoint_sha256")
            after = file_sha256(checkpoint) if checkpoint and checkpoint.is_file() else None
            kind = "checkpoint"
        if not before or not after or before == after:
            raise ValueError("reset requires a changed Task design or recorded checkpoint; a reason alone is insufficient")
        entry.setdefault("resets", []).append({
            "after_attempt": len(entry["attempts"]), "recorded_at": now,
            "reason": args.reason, "kind": kind, "before_sha256": before,
            "after_sha256": after, "artifacts": proofs,
        })
        entry["design_fingerprint"] = design_fingerprint
        entry["failure"] = None
        entry["breaker"] = {"state": "closed", "reason": None, "opened_at": None,
                            "reset_at": now, "reset_reason": args.reason}
    elif args.operation == "authorize":
        if not args.attempt_key or not args.method:
            raise ValueError("authorize requires --attempt-key and --method")
        if not unresolved(entry) or entry["breaker"]["state"] == "open":
            raise ValueError("authorize requires an unresolved failure with a closed breaker")
        if any(item["attempt_key"] == args.attempt_key or item["result"] == "pending" for item in entry["attempts"]):
            raise ValueError("recovery already reserved; reconcile its outcome, do not execute twice")
        fingerprint = entry["failure"]["fingerprint"]
        failed = failed_attempts_for(entry, fingerprint)
        if sum(item["method"] == args.method for item in failed) >= ledger["policy"]["max_same_method_failures"]:
            raise ValueError("same recovery method already failed twice; choose a new path")
        entry["attempts"].append({"attempt_key": args.attempt_key, "failure_fingerprint": fingerprint,
                                 "method": args.method, "result": "pending", "artifact_refs": [], "recorded_at": now})
    elif args.operation == "record":
        if not all((args.failure_class, args.failure_fingerprint, args.attempt_key, args.method, args.result)):
            raise ValueError("record requires --failure-class, --failure-fingerprint, --attempt-key, --method and --result")
        if entry["breaker"]["state"] == "open":
            raise ValueError("circuit breaker is open; inspect or repair the contract first")
        if args.result == "failed" and args.diagnosis_status == "resolved":
            raise ValueError("a failed recovery cannot resolve its diagnosis")
        pending = next((item for item in entry["attempts"] if item["attempt_key"] == args.attempt_key), None)
        if pending and (pending["result"] != "pending" or pending["method"] != args.method or pending["failure_fingerprint"] != args.failure_fingerprint):
            raise ValueError("record must resolve the matching pending recovery exactly once")
        if unresolved(entry) and not pending:
            raise ValueError("unresolved failure requires authorize before another recovery")
        previous_failure = entry.get("failure") or {}
        same_failure = previous_failure.get("fingerprint") == args.failure_fingerprint and unresolved(entry)
        checkpoint_ref = previous_failure.get("checkpoint_ref") if same_failure else args.checkpoint_ref
        checkpoint_hash = previous_failure.get("checkpoint_sha256") if same_failure else None
        if checkpoint_ref and not same_failure:
            checkpoint_hash = file_sha256(artifact_path(task_path, checkpoint_ref))
        entry["design_fingerprint"] = entry.get("design_fingerprint") if same_failure else design_fingerprint
        entry["failure"] = {
            "failure_class": args.failure_class, "fingerprint": args.failure_fingerprint,
            "diagnosis_status": "resolved" if args.result == "recovered" else args.diagnosis_status,
            "checkpoint_ref": checkpoint_ref, "checkpoint_sha256": checkpoint_hash,
            "next_action": args.next_action,
        }
        row = {"attempt_key": args.attempt_key, "failure_fingerprint": args.failure_fingerprint,
               "method": args.method, "result": args.result,
               "artifact_refs": list(dict.fromkeys(args.artifact_ref)), "recorded_at": now}
        if pending:
            pending.update(row)
        else:
            entry["attempts"].append(row)
        failed = failed_attempts_for(entry, args.failure_fingerprint)
        if args.result == "recovered":
            entry["breaker"].update(state="closed", reason=None, opened_at=None)
        elif len({item["method"] for item in failed}) >= ledger["policy"]["max_failed_paths"]:
            entry["breaker"].update(state="open", opened_at=now,
                                    reason="same Gate and failure fingerprint exhausted three recovery paths")
    ledger["last_updated"] = now
    errors = validate_ledger(ledger, path, schema_dir)
    if errors:
        raise ValueError("invalid Recovery Ledger:\n" + "\n".join(errors))
    atomic_write(path, ledger)
    print(json.dumps(breaker_summary(entry), ensure_ascii=False, sort_keys=True))
    return 2 if entry["breaker"]["state"] == "open" else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage a PM Gate recovery ledger.")
    parser.add_argument("task")
    parser.add_argument("operation", choices=["init", "authorize", "record", "check", "reset", "validate", "import"])
    parser.add_argument("--ledger")
    parser.add_argument("--import-ledger")
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
    if path != default_path(task_path) and args.operation not in {"check", "validate"}:
        raise ValueError("Recovery writes must use the canonical Task ledger; use import for legacy files")
    if args.operation in {"check", "validate"}:
        if not path.is_file():
            raise ValueError(f"Recovery Ledger is missing: {path}")
        return mutate(args, task_path, task, path, schema_dir)
    with ledger_lock(path):
        return mutate(args, task_path, task, path, schema_dir)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

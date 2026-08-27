#!/usr/bin/env python3
"""Build a compact derived Context Packet from Task, Runtime, and Evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_context_packet import (  # noqa: E402
    packet_digest,
    validate_context_packet,
)
from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    compose_task_runtime,
    evidence_file_for,
    load_structured_file,
    runtime_file_for,
    validate_schema,
    validate_task_runtime_layout,
)


FULL_READ_TRIGGERS = [
    "design-freeze-change",
    "safety-boundary-change",
    "contract-review",
    "schema-migration",
    "terminal-closure",
    "forensic-diagnosis",
]
ACTIVE_STATUSES = {"queued", "running"}
FORBIDDEN_MARKERS = ("禁止", "不得", "不允许", "严禁", "must not", "forbid")


def compact_text(value: Any, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def compact_list(values: Iterable[Any], *, item_limit: int, count_limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = compact_text(value, item_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= count_limit:
            break
    return result


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(path: Path | None, output_path: Path) -> dict[str, str] | None:
    if path is None or not path.exists():
        return None
    relative = os.path.relpath(path.resolve(), output_path.parent.resolve())
    return {"path": relative, "sha256": sha256_file(path)}


def select_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    active = [run for run in runs if run.get("status") in ACTIVE_STATUSES]
    if active:
        return active[-1]
    return runs[-1] if runs else None


def select_attempt(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    attempts = [item for item in run.get("attempts", []) if isinstance(item, dict)]
    active = [item for item in attempts if item.get("status") in ACTIVE_STATUSES]
    if active:
        return active[-1]
    return attempts[-1] if attempts else None


def milestone_from_attempt(attempt: dict[str, Any] | None) -> dict[str, Any] | None:
    lease = (attempt or {}).get("lease")
    if not isinstance(lease, dict):
        return None
    if not any(
        lease.get(field) is not None
        for field in ("progress_seq", "last_progress_at", "last_progress_summary", "event_cursor")
    ):
        return None
    return {
        "progress_seq": int(lease.get("progress_seq") or 0),
        "last_progress_at": lease.get("last_progress_at"),
        "summary": (
            compact_text(lease.get("last_progress_summary"), 500)
            if lease.get("last_progress_summary")
            else None
        ),
        "event_cursor": lease.get("event_cursor"),
    }


def facts_from_evidence(evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not evidence:
        return []
    facts: list[dict[str, Any]] = []
    levels = evidence.get("verification", {}).get("levels", {})
    for level in ("L4", "L3", "L2", "L1", "L0"):
        data = levels.get(level) or {}
        status = data.get("status")
        summary = compact_text(data.get("summary"), 350)
        if status not in {"pass", "pass_mock"} or not summary:
            continue
        facts.append(
            {
                "claim": f"{level}: {summary}",
                "status": status,
                "artifact_ids": compact_list(
                    data.get("evidence_refs", []), item_limit=120, count_limit=6
                ),
            }
        )
    for check in evidence.get("quality_checks", []):
        if not isinstance(check, dict) or check.get("status") != "passed":
            continue
        summary = compact_text(check.get("summary"), 300)
        if not summary:
            continue
        facts.append(
            {
                "claim": f"质量检查 {check.get('id')}: {summary}",
                "status": "pass",
                "artifact_ids": compact_list(
                    check.get("evidence_refs", []), item_limit=120, count_limit=6
                ),
            }
        )
        if len(facts) >= 8:
            break
    return facts[:8]


def open_blockers_from_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for blocker in task.get("blockers", []):
        if not isinstance(blocker, dict) or blocker.get("status") != "open":
            continue
        blockers.append(
            {
                "id": str(blocker.get("id") or "unknown-blocker"),
                "type": str(blocker.get("type") or "unknown"),
                "cause": str(blocker.get("cause") or "unknown"),
                "hard": blocker.get("hard") is True,
                "description": compact_text(blocker.get("description"), 350),
                "next_unblock_action": (
                    compact_text(blocker.get("next_unblock_action"), 350)
                    if blocker.get("next_unblock_action")
                    else None
                ),
            }
        )
        if len(blockers) >= 5:
            break
    return blockers


def failure_from_blockers(
    task: dict[str, Any], blockers: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if not blockers:
        return None
    source = next((item for item in blockers if item["hard"]), blockers[0])
    original = next(
        (
            item
            for item in task.get("blockers", [])
            if isinstance(item, dict) and item.get("id") == source["id"]
        ),
        {},
    )
    return {
        "failure_class": source["cause"],
        "failure_phase": str(task.get("lifecycle", {}).get("phase") or "unknown"),
        "diagnosis_status": "unknown",
        "fingerprint": None,
        "repeat_count": int(original.get("recovery_attempts") or 0),
        "checkpoint_ref": None,
        "forbidden_retries": [],
        "next_diagnostic_action": source.get("next_unblock_action"),
    }


def evidence_gaps(task: dict[str, Any], evidence: dict[str, Any] | None) -> list[str]:
    values: list[Any] = list(task.get("verification", {}).get("missing", []))
    if evidence:
        values.extend(evidence.get("verification", {}).get("uncovered_items", []))
        for check in evidence.get("quality_checks", []):
            if not isinstance(check, dict) or check.get("status") not in {
                "pending",
                "failed",
                "blocked",
            }:
                continue
            values.append(
                f"质量检查 {check.get('id')}: "
                f"{compact_text(check.get('summary') or check.get('status'), 300)}"
            )
    return compact_list(values, item_limit=300, count_limit=10)


def shrink_packet(packet: dict[str, Any]) -> None:
    packet["objective"] = compact_text(packet.get("objective"), 500)
    for key in ("allowed", "prohibited", "constraints"):
        packet["scope"][key] = compact_list(
            packet.get("scope", {}).get(key, []), item_limit=220, count_limit=5
        )
    compact_facts = []
    for fact in packet.get("confirmed_facts", [])[:5]:
        compact_facts.append(
            {
                "claim": compact_text(fact.get("claim"), 240),
                "status": fact.get("status"),
                "artifact_ids": list(fact.get("artifact_ids", []))[:4],
            }
        )
    packet["confirmed_facts"] = compact_facts
    packet["open_blockers"] = packet.get("open_blockers", [])[:3]
    for blocker in packet["open_blockers"]:
        blocker["description"] = compact_text(blocker.get("description"), 220)
        if blocker.get("next_unblock_action"):
            blocker["next_unblock_action"] = compact_text(
                blocker["next_unblock_action"], 220
            )
    packet["dependencies"] = packet.get("dependencies", [])[:6]
    packet["locks"] = packet.get("locks", [])[:4]
    for lock in packet["locks"]:
        lock["scope"] = compact_text(lock.get("scope"), 220)
    packet["evidence_gaps"] = compact_list(
        packet.get("evidence_gaps", []), item_limit=220, count_limit=6
    )


def build_context_packet(
    task_path: Path,
    output_path: Path,
    *,
    mode: str = "initial",
    objective: str | None = None,
    gate: str | None = None,
    allowed_scope: list[str] | None = None,
    prohibited_scope: list[str] | None = None,
    verification_commands: list[str] | None = None,
    packet_max_chars: int = 8000,
    initial_prompt_max_chars: int = 6000,
    continuation_prompt_max_chars: int = 3000,
    full_read_trigger: str | None = None,
    generated_at: str | None = None,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], str]:
    task_path = task_path.resolve()
    output_path = output_path.resolve()
    schema_dir = schema_dir or SCRIPT_DIR.parent / "references" / "schemas"
    task_schema = load_structured_file(schema_dir / "task.schema.json")
    runtime_schema = load_structured_file(schema_dir / "runtime.schema.json")
    evidence_schema = load_structured_file(schema_dir / "evidence.schema.json")
    context_schema = load_structured_file(schema_dir / "context-packet.schema.json")
    for name, schema in (
        ("task.schema.json", task_schema),
        ("runtime.schema.json", runtime_schema),
        ("evidence.schema.json", evidence_schema),
        ("context-packet.schema.json", context_schema),
    ):
        assert_supported_schema(schema, name)

    task = load_structured_file(task_path)
    source_errors = validate_schema(task, task_schema, str(task_path), task_schema)
    runtime_path = runtime_file_for(task_path, task, None)
    runtime = None
    if runtime_path and runtime_path.exists():
        runtime = load_structured_file(runtime_path)
        source_errors.extend(
            validate_schema(runtime, runtime_schema, str(runtime_path), runtime_schema)
        )
    source_errors.extend(validate_task_runtime_layout(task, runtime, str(task_path)))
    evidence_path = evidence_file_for(task_path, task, None)
    evidence = None
    if evidence_path.exists():
        evidence = load_structured_file(evidence_path)
        source_errors.extend(
            validate_schema(evidence, evidence_schema, str(evidence_path), evidence_schema)
        )
    if source_errors:
        raise ValueError("invalid PM sources:\n" + "\n".join(source_errors))

    effective = compose_task_runtime(task, runtime)
    run = select_run(effective.get("runs", []))
    attempt = select_attempt(run)
    design_freeze = effective.get("dispatch", {}).get("design_freeze") or {}
    lifecycle = effective.get("lifecycle", {})
    next_action = lifecycle.get("next_action")
    accepted_scope = lifecycle.get("accepted_scope")
    if objective:
        packet_objective = compact_text(objective, 700)
    elif mode == "continuation" and next_action:
        packet_objective = compact_text(next_action, 700)
    else:
        packet_objective = compact_text(accepted_scope or effective.get("title"), 700)

    all_constraints = compact_list(
        design_freeze.get("constraints", []), item_limit=350, count_limit=10
    )
    derived_prohibited = [
        item
        for item in all_constraints
        if any(marker.lower() in item.lower() for marker in FORBIDDEN_MARKERS)
    ]
    constraints = [item for item in all_constraints if item not in derived_prohibited]
    allowed = compact_list(
        list(design_freeze.get("scope", [])) + list(allowed_scope or []),
        item_limit=350,
        count_limit=10,
    )
    if not allowed:
        allowed = ["任务定义的 " + "/".join(effective.get("area", [])) + " 范围"]
    prohibited = compact_list(
        derived_prohibited + list(prohibited_scope or []),
        item_limit=350,
        count_limit=10,
    )

    blockers = open_blockers_from_task(effective)
    dependencies = []
    for dependency in effective.get("dependencies", {}).get("requires", [])[:10]:
        if not isinstance(dependency, dict):
            continue
        dependencies.append(
            {
                "task_id": str(dependency.get("task_id") or ""),
                "required_status": str(dependency.get("required_status") or "unknown"),
                "current_status": dependency.get("status"),
                "evidence_ref": dependency.get("evidence_ref"),
            }
        )
    locks = []
    for lock in effective.get("resources", {}).get("locks", []):
        if not isinstance(lock, dict) or lock.get("status") != "active":
            continue
        locks.append(
            {
                "resource_id": str(lock.get("resource_id") or "unknown-resource"),
                "mode": str(lock.get("mode") or "exclusive"),
                "status": "active",
                "holder_run_id": str(lock.get("holder_run_id") or "unknown-run"),
                "lease_expires_at": lock.get("lease_expires_at"),
                "scope": compact_text(lock.get("scope"), 300),
            }
        )

    packet: dict[str, Any] = {
        "schema_version": "1",
        "derived": True,
        "mode": mode,
        "task": {
            "id": effective["id"],
            "schema_version": str(task.get("schema_version")),
            "display_name": effective["display_name"],
            "title": effective["title"],
            "priority": effective["priority"],
            "status": effective["status"],
            "area": list(effective.get("area", [])),
        },
        "execution": {
            "run_id": run.get("run_id") if run else None,
            "run_status": run.get("status") if run else None,
            "attempt_id": attempt.get("attempt_id") if attempt else None,
            "attempt_status": attempt.get("status") if attempt else None,
            "gate": gate or (run.get("gate") if run else None),
            "design_fingerprint": (
                run.get("design_fingerprint") if run else design_freeze.get("fingerprint")
            ),
            "latest_milestone": milestone_from_attempt(attempt),
        },
        "objective": packet_objective,
        "scope": {
            "allowed": allowed,
            "prohibited": prohibited,
            "constraints": constraints,
        },
        "confirmed_facts": facts_from_evidence(evidence),
        "open_failure": failure_from_blockers(effective, blockers),
        "open_blockers": blockers,
        "dependencies": dependencies,
        "locks": locks,
        "evidence_gaps": evidence_gaps(effective, evidence),
        "verification_commands": compact_list(
            verification_commands or [], item_limit=500, count_limit=8
        ),
        "budgets": {
            "packet_max_chars": packet_max_chars,
            "initial_prompt_max_chars": initial_prompt_max_chars,
            "continuation_prompt_max_chars": continuation_prompt_max_chars,
            "full_read_allowed": full_read_trigger is not None,
            "full_read_trigger": full_read_trigger,
            "full_read_triggers": FULL_READ_TRIGGERS,
        },
        "source_digests": {
            "task": source_digest(task_path, output_path),
            "runtime": source_digest(runtime_path, output_path),
            "evidence": source_digest(evidence_path if evidence_path.exists() else None, output_path),
        },
        "generated_at": generated_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "packet_sha256": "",
    }
    packet["packet_sha256"] = packet_digest(packet)
    rendered = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(rendered) > packet_max_chars:
        shrink_packet(packet)
        packet["packet_sha256"] = packet_digest(packet)
        rendered = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    errors = validate_context_packet(
        packet,
        packet_path=output_path,
        schema=context_schema,
        packet_text=rendered,
        check_sources=True,
    )
    if errors:
        raise ValueError("invalid Context Packet:\n" + "\n".join(errors))
    return packet, rendered


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one derived PM Context Packet.")
    parser.add_argument("task", help="Path to docs/tasks/<TASK>/task.yaml")
    parser.add_argument("--output", help="Defaults to <task-dir>/context/active-context.json")
    parser.add_argument("--mode", choices=["initial", "continuation"], default="initial")
    parser.add_argument("--objective")
    parser.add_argument(
        "--gate",
        choices=["contract", "implementation", "integration", "verification", "closure"],
    )
    parser.add_argument("--allowed-scope", action="append", default=[])
    parser.add_argument("--prohibited-scope", action="append", default=[])
    parser.add_argument("--verification-command", action="append", default=[])
    parser.add_argument("--packet-max-chars", type=int, default=8000)
    parser.add_argument("--initial-prompt-max-chars", type=int, default=6000)
    parser.add_argument("--continuation-prompt-max-chars", type=int, default=3000)
    parser.add_argument("--allow-full-read", choices=FULL_READ_TRIGGERS)
    parser.add_argument("--now", help="Stable generated_at for tests or reproducible builds")
    args = parser.parse_args()

    task_path = Path(args.task).resolve()
    output_path = (
        Path(args.output).resolve()
        if args.output
        else task_path.parent / "context" / "active-context.json"
    )
    packet, rendered = build_context_packet(
        task_path,
        output_path,
        mode=args.mode,
        objective=args.objective,
        gate=args.gate,
        allowed_scope=args.allowed_scope,
        prohibited_scope=args.prohibited_scope,
        verification_commands=args.verification_command,
        packet_max_chars=args.packet_max_chars,
        initial_prompt_max_chars=args.initial_prompt_max_chars,
        continuation_prompt_max_chars=args.continuation_prompt_max_chars,
        full_read_trigger=args.allow_full_read,
        generated_at=args.now,
    )
    atomic_write(output_path, rendered)
    print(f"Wrote {output_path}")
    print(packet["packet_sha256"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

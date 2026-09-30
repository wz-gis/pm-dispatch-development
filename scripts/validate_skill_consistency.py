#!/usr/bin/env python3
"""Check cross-file PM Dispatch protocol invariants."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEARTBEAT_MINUTES = 10
EXPECTED_PROTOCOL_VERSION = "2"
EXPECTED_CODEX_ADAPTER_VERSION = "15"
EXPECTED_CODEX_WAIT_POLICY = {
    "max_calls_per_run": 1,
    "max_timeout_ms": 30000,
    "allowed_sources": ["coordinator"],
}
WORKER_OPERATIONS = {"create", "send", "inspect", "wait", "rebind", "collect", "cancel"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_consistency(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    schema_dir = root / "references" / "schemas"
    task_schema = load_json(schema_dir / "task.schema.json")
    runtime_schema = load_json(schema_dir / "runtime.schema.json")
    adapter_schema = load_json(schema_dir / "adapter.schema.json")
    context_schema = load_json(schema_dir / "context-packet.schema.json")
    coordinator_schema = load_json(schema_dir / "coordinator-budget.schema.json")

    task_interval = (
        task_schema["properties"]["dispatch"]["properties"]["heartbeat"]
        ["properties"]["interval_minutes"]["enum"]
    )
    runtime_interval = (
        runtime_schema["$defs"]["heartbeat"]["properties"]
        ["interval_minutes"]["enum"]
    )
    for label, values in (
        ("task.schema.json", task_interval),
        ("runtime.schema.json", runtime_interval),
    ):
        if values != [EXPECTED_HEARTBEAT_MINUTES]:
            errors.append(
                f"{label}: heartbeat interval must be [{EXPECTED_HEARTBEAT_MINUTES}]"
            )

    forbidden_five_minute_claim = re.compile(
        r"(?:每|exactly\s+|every\s+|same\s+)\s*(?:固定\s*)?5\s*(?:分钟|minute)",
        re.IGNORECASE,
    )
    documents = [root / "SKILL.md", *sorted(root.glob("README*.md"))]
    documents.extend(sorted((root / "references").rglob("*.md")))
    for path in documents:
        text = path.read_text(encoding="utf-8")
        if forbidden_five_minute_claim.search(text):
            errors.append(f"{path.relative_to(root)}: active monitoring still claims 5 minutes")

    protocol_versions = adapter_schema["properties"]["protocol_version"]["enum"]
    if protocol_versions != [EXPECTED_PROTOCOL_VERSION]:
        errors.append("adapter.schema.json: protocol_version must be [\"2\"]")
    required_operations = set(
        adapter_schema["properties"]["components"]["properties"]["worker"]["required"]
    )
    if not WORKER_OPERATIONS.issubset(required_operations):
        errors.append("adapter.schema.json: Worker operation set is incomplete")
    for path in sorted((root / "references" / "adapters").glob("*.adapter.json")):
        adapter = load_json(path)
        if adapter.get("protocol_version") != EXPECTED_PROTOCOL_VERSION:
            errors.append(f"{path.name}: protocol_version is not 2")
        worker = adapter.get("components", {}).get("worker", {})
        missing = WORKER_OPERATIONS - set(worker)
        if missing:
            errors.append(f"{path.name}: missing operations {sorted(missing)}")
        if adapter.get("provider") == "codex":
            worker = adapter.get("components", {}).get("worker", {})
            monitor = adapter.get("components", {}).get("monitor", {})
            if worker.get("visibility") != "user-visible" or (worker.get("create") or {}).get("target") != "create_thread":
                errors.append("codex.adapter.json: dispatch must create a user-visible thread")
            if monitor.get("heartbeat_operation") != "automation_update" or monitor.get("coordinator_binding") != "current-conversation":
                errors.append("codex.adapter.json: heartbeat must bind to the current conversation")
            inspect = worker.get("inspect") or {}
            wait = worker.get("wait") or {}
            if adapter.get("adapter_version") != EXPECTED_CODEX_ADAPTER_VERSION:
                errors.append("codex.adapter.json: adapter_version must be 15")
            if monitor.get("modes") != ["heartbeat"]:
                errors.append("codex.adapter.json: visible Workers require heartbeat-only monitoring")
            if inspect.get("target") != "wait_threads" or inspect.get("fixed_inputs") != {"timeout_ms": 0}:
                errors.append("codex.adapter.json: inspect must be a zero-wait snapshot")
            if wait.get("target") != "wait_threads" or "timeout_ms" not in set(wait.get("input_fields") or []):
                errors.append("codex.adapter.json: terminal wait requires explicit timeout_ms")
            if wait.get("call_policy") != EXPECTED_CODEX_WAIT_POLICY or wait.get("timeout_seconds") != 30:
                errors.append("codex.adapter.json: terminal wait must be single-short")
            if monitor.get("inspection_interval_seconds") != 600:
                errors.append("codex.adapter.json: inspection interval must be 600 seconds")
            if monitor.get("max_inspections_per_cycle") != 1:
                errors.append("codex.adapter.json: one inspection is allowed per cycle")
            if monitor.get("model_free_tick") != "scripts/plan_monitor_tick.py":
                errors.append("codex.adapter.json: model-free tick planner is missing")

    if "4" not in task_schema["properties"]["schema_version"]["enum"]:
        errors.append("task.schema.json: Task v4 is not declared")
    if "runtime_file" not in task_schema["properties"]:
        errors.append("task.schema.json: runtime_file is not declared")
    delegation_schema = task_schema["properties"]["dispatch"]["properties"].get(
        "delegation", {}
    )
    delegation_required = set(delegation_schema.get("required", []))
    expected_delegation_fields = {
        "mode",
        "agent",
        "initial_invocation_limit",
        "repair_invocation_limit",
        "retry_policy",
    }
    if delegation_required != expected_delegation_fields:
        errors.append("task.schema.json: delegated subagent contract is incomplete")
    if runtime_schema["properties"]["schema_version"]["enum"] != ["1"]:
        errors.append("runtime.schema.json: Runtime v1 is not declared")
    if not (schema_dir / "runtime-event.schema.json").is_file():
        errors.append("runtime-event.schema.json is missing")
    else:
        event_schema = load_json(schema_dir / "runtime-event.schema.json")
        event_types = set(event_schema["properties"]["event_type"]["enum"])
        if not {
            "terminal-wait-authorized",
            "terminal-wait-finished",
            "status-inspect-authorized",
            "dispatch-provisioning-started",
            "dispatch-provisioning-completed",
            "dispatch-provisioning-rolled-back",
        }.issubset(
            event_types
        ):
            errors.append("runtime-event.schema.json: control-plane events are missing")
    wait_budget = runtime_schema["$defs"].get("wait_budget", {})
    if wait_budget.get("properties", {}).get("max_timeout_ms", {}).get("enum") != [30000]:
        errors.append("runtime.schema.json: wait budget must cap timeout at 30000 ms")
    if context_schema["properties"]["schema_version"]["enum"] != ["1"]:
        errors.append("context-packet.schema.json: Context Packet v1 is not declared")
    if coordinator_schema["properties"]["schema_version"]["enum"] != ["1"]:
        errors.append("coordinator-budget.schema.json: Coordinator Budget v1 is not declared")
    context_execution = context_schema["properties"]["execution"]
    if "delegation" not in context_execution["required"]:
        errors.append("context-packet.schema.json: execution.delegation is not required")
    if not (root / "references" / "delegated-subagent.md").is_file():
        errors.append("references/delegated-subagent.md is missing")
    required_packet_fields = {
        "task",
        "execution",
        "objective",
        "confirmed_facts",
        "evidence_gaps",
        "budgets",
        "source_digests",
        "packet_sha256",
    }
    if not required_packet_fields.issubset(set(context_schema["required"])):
        errors.append("context-packet.schema.json: required compact context fields are incomplete")
    required_source_digests = {
        "task",
        "runtime",
        "evidence",
        "evidence_digest",
        "project_snapshot",
        "recovery_ledger",
    }
    if not required_source_digests.issubset(
        set(context_schema["properties"]["source_digests"]["required"])
    ):
        errors.append("context-packet.schema.json: derived source digest fields are incomplete")
    for script_name in (
        "build_context_packet.py",
        "validate_context_packet.py",
        "measure_context_baseline.py",
        "build_evidence_digest.py",
        "validate_evidence_digest.py",
        "build_project_snapshot.py",
        "manage_recovery_ledger.py",
        "dispatch_preflight.py",
        "authorize_terminal_wait.py",
        "authorize_status_inspect.py",
        "complete_status_inspect.py",
        "check_coordinator_budget.py",
        "manage_dispatch_transaction.py",
        "plan_monitor_tick.py",
    ):
        if not (root / "scripts" / script_name).is_file():
            errors.append(f"scripts/{script_name} is missing")
    return errors


def main() -> int:
    errors = validate_consistency()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("PM dispatch skill consistency passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

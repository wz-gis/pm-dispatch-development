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
    documents = [root / "SKILL.md", root / "README.md", root / "README.en.md"]
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

    if "4" not in task_schema["properties"]["schema_version"]["enum"]:
        errors.append("task.schema.json: Task v4 is not declared")
    if "runtime_file" not in task_schema["properties"]:
        errors.append("task.schema.json: runtime_file is not declared")
    if runtime_schema["properties"]["schema_version"]["enum"] != ["1"]:
        errors.append("runtime.schema.json: Runtime v1 is not declared")
    if not (schema_dir / "runtime-event.schema.json").is_file():
        errors.append("runtime-event.schema.json is missing")
    if context_schema["properties"]["schema_version"]["enum"] != ["1"]:
        errors.append("context-packet.schema.json: Context Packet v1 is not declared")
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
    for script_name in (
        "build_context_packet.py",
        "validate_context_packet.py",
        "measure_context_baseline.py",
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

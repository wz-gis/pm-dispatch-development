#!/usr/bin/env python3
"""Validate a derived PM Context Packet and optional Worker prompt."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
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


FULL_READ_PATTERNS = (
    re.compile(
        r"(?:完整|全文|全量).{0,20}(?:读取|重读).{0,80}"
        r"(?:Task|Evidence|Runtime|历史|看板|dispatch-board)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:读取|重读).{0,20}(?:完整|全文|全量).{0,80}"
        r"(?:Task|Evidence|Runtime|历史|看板|dispatch-board)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:read|reload).{0,20}(?:full|entire|complete).{0,80}"
        r"(?:task|evidence|runtime|history|board)",
        re.IGNORECASE | re.DOTALL,
    ),
)


def canonical_packet_payload(packet: dict[str, Any]) -> bytes:
    payload = copy.deepcopy(packet)
    payload.pop("generated_at", None)
    payload.pop("packet_sha256", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def packet_digest(packet: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_packet_payload(packet)).hexdigest()


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_requests_full_read(prompt: str) -> bool:
    return any(pattern.search(prompt) for pattern in FULL_READ_PATTERNS)


def resolve_source_path(packet_path: Path, configured: str) -> Path:
    path = Path(configured)
    if path.is_absolute():
        return path
    return (packet_path.parent / path).resolve()


def validate_context_packet(
    packet: dict[str, Any],
    *,
    packet_path: Path,
    schema: dict[str, Any],
    packet_text: str | None = None,
    prompt_text: str | None = None,
    prompt_mode: str | None = None,
    check_sources: bool = True,
) -> list[str]:
    errors = validate_schema(packet, schema, str(packet_path), schema)
    if errors:
        return errors

    expected_digest = packet_digest(packet)
    if packet.get("packet_sha256") != expected_digest:
        errors.append(
            f"{packet_path}: packet_sha256 mismatch; expected {expected_digest}"
        )

    budgets = packet.get("budgets", {})
    if packet_text is not None and len(packet_text) > budgets.get("packet_max_chars", 0):
        errors.append(
            f"{packet_path}: packet has {len(packet_text)} chars; maximum is "
            f"{budgets.get('packet_max_chars')}"
        )

    full_read_allowed = budgets.get("full_read_allowed") is True
    full_read_trigger = budgets.get("full_read_trigger")
    if full_read_allowed and not full_read_trigger:
        errors.append(f"{packet_path}: full_read_allowed requires full_read_trigger")
    if not full_read_allowed and full_read_trigger is not None:
        errors.append(f"{packet_path}: full_read_trigger requires full_read_allowed=true")
    if full_read_trigger and full_read_trigger not in budgets.get("full_read_triggers", []):
        errors.append(f"{packet_path}: full_read_trigger is not declared in full_read_triggers")

    if check_sources:
        for source_name, source in packet.get("source_digests", {}).items():
            if source is None:
                continue
            source_path = resolve_source_path(packet_path, str(source.get("path") or ""))
            if not source_path.is_file():
                errors.append(f"{packet_path}: {source_name} source is missing: {source_path}")
                continue
            actual = file_digest(source_path)
            if source.get("sha256") != actual:
                errors.append(
                    f"{packet_path}: {source_name} source digest drift; expected "
                    f"{source.get('sha256')}, got {actual}"
                )
        task_source = packet.get("source_digests", {}).get("task")
        if task_source:
            task_path = resolve_source_path(packet_path, task_source["path"])
            if task_path.is_file():
                task = load_structured_file(task_path)
                if task.get("id") != packet.get("task", {}).get("id"):
                    errors.append(
                        f"{packet_path}: packet task id does not match source task"
                    )

    if prompt_text is not None:
        mode = prompt_mode or str(packet.get("mode") or "initial")
        budget_key = (
            "continuation_prompt_max_chars"
            if mode == "continuation"
            else "initial_prompt_max_chars"
        )
        prompt_budget = int(budgets.get(budget_key) or 0)
        if len(prompt_text) > prompt_budget:
            errors.append(
                f"{packet_path}: {mode} prompt has {len(prompt_text)} chars; "
                f"maximum is {prompt_budget}"
            )
        if prompt_requests_full_read(prompt_text) and not full_read_allowed:
            errors.append(
                f"{packet_path}: prompt requests a full Task/Evidence/history read "
                "without an allowed trigger"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one PM Context Packet.")
    parser.add_argument("packet", help="Path to context packet JSON")
    parser.add_argument("--schema", help="Override context-packet.schema.json")
    parser.add_argument("--prompt", help="Optional Worker prompt to validate")
    parser.add_argument("--mode", choices=["initial", "continuation"])
    parser.add_argument("--no-source-check", action="store_true")
    args = parser.parse_args()

    packet_path = Path(args.packet).resolve()
    schema_path = (
        Path(args.schema).resolve()
        if args.schema
        else SCRIPT_DIR.parent / "references" / "schemas" / "context-packet.schema.json"
    )
    packet_text = packet_path.read_text(encoding="utf-8")
    packet = load_structured_file(packet_path)
    schema = load_structured_file(schema_path)
    assert_supported_schema(schema, str(schema_path))
    prompt_text = (
        Path(args.prompt).resolve().read_text(encoding="utf-8")
        if args.prompt
        else None
    )
    errors = validate_context_packet(
        packet,
        packet_path=packet_path,
        schema=schema,
        packet_text=packet_text,
        prompt_text=prompt_text,
        prompt_mode=args.mode,
        check_sources=not args.no_source_check,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("PM context packet validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

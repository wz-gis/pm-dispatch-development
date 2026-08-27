#!/usr/bin/env python3
"""Build and decode versioned Worker Adapter protocol envelopes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class AdapterProtocolError(ValueError):
    """Raised when an Adapter operation cannot be built or decoded safely."""


def build_invocation(
    adapter: dict[str, Any],
    operation_name: str,
    inputs: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if adapter.get("protocol_version") != "2":
        raise AdapterProtocolError(
            f"unsupported protocol_version {adapter.get('protocol_version')!r}"
        )
    worker = adapter.get("components", {}).get("worker", {})
    operation = worker.get(operation_name)
    if not isinstance(operation, dict):
        raise AdapterProtocolError(f"unknown worker operation {operation_name!r}")

    required = list(operation.get("input_fields", []))
    optional = list(operation.get("optional_input_fields", []))
    declared = set(required) | set(optional)
    provided = set(inputs)
    missing = sorted(set(required) - provided)
    undeclared = sorted(provided - declared)
    if missing:
        raise AdapterProtocolError(f"{operation_name} missing inputs: {', '.join(missing)}")
    if undeclared:
        raise AdapterProtocolError(
            f"{operation_name} received undeclared inputs: {', '.join(undeclared)}"
        )

    idempotency = operation.get("idempotency")
    if idempotency == "required" and not idempotency_key:
        raise AdapterProtocolError(f"{operation_name} requires an idempotency key")
    envelope = {
        "protocol_version": adapter["protocol_version"],
        "adapter_version": adapter["adapter_version"],
        "provider": adapter["provider"],
        "operation": operation_name,
        "transport": worker["transport"],
        "target": operation["target"],
        "inputs": {
            field: inputs[field]
            for field in required + optional
            if field in inputs
        },
        "timeout_seconds": operation["timeout_seconds"],
    }
    if idempotency_key:
        envelope["idempotency_key"] = idempotency_key
    return envelope


def extract_operation_result(
    adapter: dict[str, Any], operation_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    operation = adapter.get("components", {}).get("worker", {}).get(operation_name)
    if not isinstance(operation, dict):
        raise AdapterProtocolError(f"unknown worker operation {operation_name!r}")
    result_paths = operation.get("result_paths") or {}
    raw_status = extract_path(payload, result_paths.get("status"))
    status = normalize_status(adapter, raw_status)
    worker_id_path = result_paths.get("worker_id")
    worker_id = extract_path(payload, worker_id_path) if worker_id_path else None
    if operation_name == "create" and not worker_id:
        raise AdapterProtocolError("create result did not contain a worker id")
    result = {"worker_id": worker_id, "status": status}
    for field in ("continuation_token", "event_cursor", "delegation"):
        path = result_paths.get(field)
        result[field] = extract_optional_path(payload, path)
    return result


def normalize_status(adapter: dict[str, Any], raw_status: Any) -> str:
    raw = str(raw_status)
    mappings = adapter.get("status_map") or []
    for mapping in mappings:
        if mapping.get("provider_status") == raw:
            return str(mapping["core_status"])
    raise AdapterProtocolError(f"unmapped provider status {raw!r}")


def extract_path(payload: dict[str, Any], path: str | None) -> Any:
    if path == "$":
        return payload
    if not path or not path.startswith("$."):
        raise AdapterProtocolError(f"invalid output path {path!r}")
    value: Any = payload
    for part in path[2:].split("."):
        if not isinstance(value, dict) or part not in value:
            raise AdapterProtocolError(f"provider result is missing {path!r}")
        value = value[part]
    return value


def extract_optional_path(payload: dict[str, Any], path: str | None) -> Any:
    if not path:
        return None
    try:
        return extract_path(payload, path)
    except AdapterProtocolError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or decode a Worker Adapter operation.")
    parser.add_argument("adapter", help="Path to one *.adapter.json file")
    parser.add_argument(
        "operation",
        choices=["create", "send", "inspect", "wait", "rebind", "collect", "cancel"],
    )
    parser.add_argument("--inputs", default="{}", help="JSON object with operation inputs")
    parser.add_argument("--idempotency-key", help="Stable key for a mutating operation")
    parser.add_argument("--result", help="Optional provider result JSON to decode")
    args = parser.parse_args()

    adapter = json.loads(Path(args.adapter).read_text(encoding="utf-8"))
    if args.result is not None:
        output = extract_operation_result(adapter, args.operation, json.loads(args.result))
    else:
        output = build_invocation(
            adapter,
            args.operation,
            json.loads(args.inputs),
            args.idempotency_key,
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AdapterProtocolError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

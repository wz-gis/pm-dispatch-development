#!/usr/bin/env python3
"""Build and decode versioned Worker Adapter protocol envelopes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from select_codex_execution import native_bindings  # noqa: E402


class AdapterProtocolError(ValueError):
    """Raised when an Adapter operation cannot be built or decoded safely."""


def build_invocation(
    adapter: dict[str, Any],
    operation_name: str,
    inputs: dict[str, Any],
    idempotency_key: str | None = None,
    source: str = "coordinator",
    host_tools: list[str] | dict | None = None,
) -> dict[str, Any]:
    if adapter.get("protocol_version") != "2":
        raise AdapterProtocolError(
            f"unsupported protocol_version {adapter.get('protocol_version')!r}"
        )
    worker = adapter.get("components", {}).get("worker", {})
    operation = worker.get(operation_name)
    if not isinstance(operation, dict):
        raise AdapterProtocolError(f"unknown worker operation {operation_name!r}")
    if operation.get("supported") is False:
        raise AdapterProtocolError(f"{operation_name} is not supported by this Adapter; use received events")

    required = list(operation.get("input_fields", []))
    optional = list(operation.get("optional_input_fields", []))
    fixed = operation.get("fixed_inputs") or {}
    if not isinstance(fixed, dict):
        raise AdapterProtocolError(f"{operation_name} fixed_inputs must be an object")
    declared = set(required) | set(optional)
    provided = set(inputs)
    fixed_overrides = sorted(provided & set(fixed))
    if fixed_overrides:
        raise AdapterProtocolError(
            f"{operation_name} cannot override fixed inputs: "
            f"{', '.join(fixed_overrides)}"
        )
    missing = sorted(set(required) - provided)
    undeclared = sorted(provided - declared - set(fixed))
    if missing:
        raise AdapterProtocolError(f"{operation_name} missing inputs: {', '.join(missing)}")
    if undeclared:
        raise AdapterProtocolError(
            f"{operation_name} received undeclared inputs: {', '.join(undeclared)}"
        )
    if adapter.get("provider") == "codex" and operation_name == "wait":
        timeout_ms = inputs.get("timeout_ms")
        if (
            not isinstance(timeout_ms, int)
            or isinstance(timeout_ms, bool)
            or timeout_ms <= 0
        ):
            raise AdapterProtocolError("Codex terminal wait requires timeout_ms > 0")
    call_policy = operation.get("call_policy") or {}
    if call_policy:
        allowed_sources = set(call_policy.get("allowed_sources") or [])
        if source not in allowed_sources:
            raise AdapterProtocolError(
                f"{operation_name} is not allowed from source {source!r}"
            )
        max_timeout_ms = call_policy.get("max_timeout_ms")
        timeout_ms = inputs.get("timeout_ms")
        if (
            isinstance(max_timeout_ms, int)
            and isinstance(timeout_ms, int)
            and not isinstance(timeout_ms, bool)
            and timeout_ms > max_timeout_ms
        ):
            raise AdapterProtocolError(
                f"{operation_name} timeout_ms exceeds {max_timeout_ms}"
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
        } | fixed,
        "timeout_seconds": operation["timeout_seconds"],
    }
    if idempotency_key:
        envelope["idempotency_key"] = idempotency_key
    if adapter.get("provider") == "codex-subagent":
        worker_id = inputs.get("worker_id")
        if operation_name == "create":
            native = {"message": inputs["prompt"]}
        elif operation_name == "send":
            native = {"target": worker_id, "message": inputs["prompt"]}
            if "interrupt" in inputs:
                native["interrupt"] = inputs["interrupt"]
        elif operation_name == "wait":
            timeout = inputs["timeout_ms"]
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not 10000 <= timeout <= 30000:
                raise AdapterProtocolError("native agent wait requires 10000..30000 ms")
            native = {"targets": [worker_id], "timeout_ms": timeout}
        else:
            native = {"target": worker_id}
        if host_tools is not None:
            binding = native_bindings(host_tools)[0].get(operation_name)
            if not binding or binding.get("needs_schema_binding"):
                raise AdapterProtocolError(f"{operation_name} has no verified host binding")
            fields = binding["input_map"]
            if set(inputs) - set(fields):
                raise AdapterProtocolError(f"{operation_name} host does not map inputs {sorted(set(inputs) - set(fields))}")
            native = {fields[key]: [value] if key in binding["list_inputs"] else value
                      for key, value in inputs.items()}
            envelope["target"] = binding["tool"]
        envelope["native_arguments"] = native
    return envelope


def extract_operation_result(
    adapter: dict[str, Any], operation_name: str, payload: dict[str, Any],
    worker_id: str | None = None,
    host_tools: list[str] | dict | None = None,
) -> dict[str, Any]:
    if adapter.get("provider") == "codex-subagent":
        require_submission = True
        if host_tools is not None:
            binding = native_bindings(host_tools)[0].get("wait" if operation_name == "collect" else operation_name)
            if binding and not binding.get("needs_schema_binding"):
                normalized = dict(payload)
                for key, path in binding["result_paths"].items():
                    normalized["agent_id" if key == "worker_id" else key] = extract_path(payload, path)
                payload = normalized
                require_submission = binding["tool"].rsplit("__", 1)[-1].rsplit(".", 1)[-1] == "send_input"
        return extract_subagent_result(operation_name, payload, worker_id, require_submission)
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
    if adapter.get("provider") == "codex":
        provider_status = raw_status.get("type") if isinstance(raw_status, dict) else raw_status
        if provider_status in {"idle", "interrupted"}:
            latest_turn = payload.get("latestTurn") or payload.get("latest_turn") or {}
            turn_status = latest_turn.get("status") if isinstance(latest_turn, dict) else None
            result["probe_status"] = "interrupted" if turn_status == "interrupted" else provider_status
            result["requires_reconciliation"] = True
    for field in ("continuation_token", "event_cursor", "delegation"):
        path = result_paths.get(field)
        result[field] = extract_optional_path(payload, path)
    return result


def extract_subagent_result(operation: str, payload: dict[str, Any], worker_id: str | None,
                            require_submission: bool = True) -> dict[str, Any]:
    result = {"worker_id": worker_id, "status": "unknown", "continuation_token": None,
              "event_cursor": None, "delegation": None, "requires_reconciliation": True}
    if operation == "create":
        if not isinstance(payload.get("agent_id"), str) or not payload["agent_id"]:
            raise AdapterProtocolError("create result did not contain an agent_id")
        return result | {"worker_id": payload["agent_id"], "status": "queued",
                         "requires_reconciliation": False}
    if not worker_id:
        raise AdapterProtocolError("native result decoding requires --worker-id")
    if operation == "send":
        if require_submission and not payload.get("submission_id"):
            raise AdapterProtocolError("send result requires submission_id")
        return result | {"submission_id": payload.get("submission_id"), "receipt": payload}
    if operation == "cancel":
        # close_agent returns the PREVIOUS status, not proof of completed shutdown.
        return result | {"previous_status": payload.get("previous_status")}
    if operation not in {"wait", "collect"}:
        raise AdapterProtocolError(f"native agent operation {operation!r} is unsupported")
    statuses = payload.get("status")
    if not isinstance(statuses, dict):
        raise AdapterProtocolError("native completion requires status keyed by agent id")
    raw = statuses.get(worker_id)
    if raw is None:
        if payload.get("timed_out") is True:
            return result
        raise AdapterProtocolError("native completion does not match the requested agent id")
    if isinstance(raw, dict) and "completed" in raw:
        return result | {"status": "succeeded", "delegation": raw["completed"],
                         "requires_reconciliation": False, "requires_acceptance": True}
    if isinstance(raw, dict) and "errored" in raw:
        return result | {"status": "failed", "delegation": raw["errored"],
                         "requires_reconciliation": False}
    if isinstance(raw, str) and raw in {"pending_init", "running", "shutdown"}:
        return result | {"status": {"pending_init": "queued", "running": "running",
                                    "shutdown": "cancelled"}[raw], "requires_reconciliation": False}
    if raw in ("interrupted", "not_found"):
        return result
    raise AdapterProtocolError(f"unmapped native agent status {raw!r}")


def normalize_status(adapter: dict[str, Any], raw_status: Any) -> str:
    raw = str(raw_status.get("type")) if isinstance(raw_status, dict) else str(raw_status)
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
    parser.add_argument(
        "--source",
        default="coordinator",
        choices=["coordinator", "heartbeat"],
        help="Invocation source used by operation call policy",
    )
    parser.add_argument("--result", help="Optional provider result JSON to decode")
    parser.add_argument("--worker-id", help="Agent id for decoding native status maps")
    parser.add_argument("--host-tools", help="Live tool inventory with verified native argument bindings")
    args = parser.parse_args()

    adapter = json.loads(Path(args.adapter).read_text(encoding="utf-8"))
    host_tools = json.loads(Path(args.host_tools).read_text()) if args.host_tools else None
    if args.result is not None:
        output = extract_operation_result(adapter, args.operation, json.loads(args.result), args.worker_id, host_tools)
    else:
        output = build_invocation(
            adapter,
            args.operation,
            json.loads(args.inputs),
            args.idempotency_key,
            args.source,
            host_tools,
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AdapterProtocolError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

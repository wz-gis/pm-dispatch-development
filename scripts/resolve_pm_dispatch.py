#!/usr/bin/env python3
"""Resolve a provider-neutral dispatch request against machine adapters."""

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
    load_adapters,
    load_structured_file,
    runtime_file_for,
    validate_schema,
)


class ResolutionError(ValueError):
    """Raised when no adapter can satisfy a dispatch request without guessing."""


def resolve_dispatch(
    dispatch: dict[str, Any], adapters: dict[str, dict[str, Any]], resolved_at: str
) -> dict[str, Any]:
    provider_policy = dispatch.get("provider_policy") or {}
    fallback = dispatch.get("fallback_policy") or {}
    profile = dispatch.get("reasoning_profile")
    policy_mode = provider_policy.get("mode")
    fallback_mode = fallback.get("mode")

    if dispatch.get("strategy") == "direct":
        raise ResolutionError("direct dispatch does not require a provider resolution")
    if not dispatch.get("required_capabilities"):
        raise ResolutionError("worker dispatch requires at least one required_capabilities entry")
    if not dispatch.get("required_evidence_kinds"):
        raise ResolutionError("worker dispatch requires at least one required_evidence_kinds entry")
    if fallback_mode == "strict" and policy_mode != "pinned":
        raise ResolutionError("strict fallback requires a pinned provider")

    providers = provider_candidates(provider_policy, fallback, adapters)
    failures: list[str] = []
    for provider in providers:
        adapter = adapters.get(provider)
        if not adapter:
            failures.append(f"{provider}: adapter is not registered")
            continue

        monitor_mode = select_monitor_mode(dispatch, adapter)
        if monitor_mode is None:
            failures.append(f"{provider}: monitoring requirement is not supported")
            continue

        required = set(dispatch.get("required_capabilities", []))
        if monitor_mode in {"manual", "milestone", "event-lease"} and "heartbeat" in required:
            required.remove("heartbeat")
        available = set(adapter.get("capabilities", []))
        missing = required - available
        if missing:
            failures.append(f"{provider}: missing capabilities {sorted(missing)}")
            continue

        required_evidence = set(dispatch.get("required_evidence_kinds", []))
        available_evidence = set(
            adapter.get("components", {}).get("evidence", {}).get("artifact_kinds", [])
        )
        missing_evidence = required_evidence - available_evidence
        if missing_evidence:
            failures.append(f"{provider}: missing evidence kinds {sorted(missing_evidence)}")
            continue

        components = adapter.get("components", {})
        model_route = components.get("model", {}).get("profiles", {}).get(profile)
        if components.get("model"):
            if not model_route:
                failures.append(f"{provider}: cannot map model route for reasoning profile {profile!r}")
                continue
            model_id = model_route["model_id"]
            provider_effort = model_route["reasoning_effort"]
        else:
            model_id = None
            provider_effort = components.get("reasoning", {}).get("profiles", {}).get(profile)
        if not provider_effort:
            failures.append(f"{provider}: cannot map reasoning profile {profile!r}")
            continue

        worker_types = adapter.get("worker_types", [])
        if not worker_types:
            failures.append(f"{provider}: no worker type is declared")
            continue

        resolved_capabilities = sorted(required)
        if monitor_mode in {"milestone", "event-lease"} and "milestone-notify" in available:
            resolved_capabilities = sorted(set(resolved_capabilities) | {"milestone-notify"})
        if monitor_mode == "event-lease":
            resolved_capabilities = sorted(
                set(resolved_capabilities) | {"lease-watchdog", "terminal-event-wait"}
            )
        if monitor_mode == "heartbeat" and "heartbeat" in available:
            resolved_capabilities = sorted(set(resolved_capabilities) | {"heartbeat"})
        return {
            "provider": provider,
            "adapter_version": str(adapter.get("adapter_version")),
            "model_id": model_id,
            "reasoning_profile": profile,
            "provider_reasoning_effort": provider_effort,
            "worker_type": worker_types[0],
            "monitor_mode": monitor_mode,
            "capabilities": resolved_capabilities,
            "evidence_kinds": sorted(required_evidence),
            "resolved_at": resolved_at,
            "reason": resolution_reason(
                policy_mode, fallback_mode, provider, model_id, monitor_mode
            ),
        }

    detail = "; ".join(failures) if failures else "no provider candidates"
    raise ResolutionError(f"no compatible provider: {detail}")


def provider_candidates(
    provider_policy: dict[str, Any],
    fallback: dict[str, Any],
    adapters: dict[str, dict[str, Any]],
) -> list[str]:
    pinned = provider_policy.get("provider")
    allowed = list(fallback.get("allowed_providers") or [])
    if provider_policy.get("mode") == "pinned":
        candidates = [str(pinned)] if pinned else []
        if fallback.get("mode") == "compatible":
            candidates.extend(provider for provider in allowed if provider not in candidates)
        return candidates
    if provider_policy.get("mode") == "auto":
        return allowed or sorted(adapters)
    return []


def select_monitor_mode(dispatch: dict[str, Any], adapter: dict[str, Any]) -> str | None:
    monitor = adapter.get("components", {}).get("monitor", {})
    modes = monitor.get("modes", [])
    capabilities = set(adapter.get("capabilities", []))
    fallback = dispatch.get("fallback_policy") or {}
    if dispatch.get("heartbeat_required"):
        if "heartbeat" in modes:
            return "heartbeat"
        if (
            "event-lease" in modes
            and monitor.get("supports_lease_renewal")
            and monitor.get("event_wait_target")
            and {"lease-watchdog", "terminal-event-wait"}.issubset(capabilities)
        ):
            return "event-lease"
        if "milestone" in modes:
            return "milestone"
        if (
            fallback.get("mode") == "compatible"
            and fallback.get("allow_manual_monitoring")
            and "manual" in modes
        ):
            return "manual"
        return None
    if (
        "event-lease" in modes
        and monitor.get("supports_lease_renewal")
        and monitor.get("event_wait_target")
        and {"lease-watchdog", "terminal-event-wait"}.issubset(capabilities)
    ):
        return "event-lease"
    for preferred in ("milestone", "poll", "manual", "heartbeat"):
        if preferred in modes:
            return preferred
    return None


def resolution_reason(
    policy_mode: str | None,
    fallback_mode: str | None,
    provider: str,
    model_id: str | None,
    monitor_mode: str,
) -> str:
    model_phrase = model_id or "inherited/provider-default model"
    return (
        f"{policy_mode or 'unknown'} provider policy with {fallback_mode or 'unknown'} fallback "
        f"selected {provider}/{model_phrase} using {monitor_mode} monitoring"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve task dispatch against provider adapters.")
    parser.add_argument("task", help="Path to task.yaml or task.json")
    parser.add_argument("--adapter-dir", help="Directory containing *.adapter.json")
    parser.add_argument("--schema-dir", help="Directory containing adapter.schema.json")
    parser.add_argument("--now", help="Resolution timestamp in ISO-8601")
    parser.add_argument("--write", action="store_true", help="Write resolution back to the task file")
    args = parser.parse_args()

    task_path = Path(args.task).resolve()
    root = SCRIPT_DIR.parent
    adapter_dir = Path(args.adapter_dir).resolve() if args.adapter_dir else root / "references" / "adapters"
    schema_dir = Path(args.schema_dir).resolve() if args.schema_dir else root / "references" / "schemas"
    adapter_schema = load_structured_file(schema_dir / "adapter.schema.json")
    assert_supported_schema(adapter_schema, "adapter.schema.json")
    adapters, errors = load_adapters(adapter_dir, adapter_schema)
    if errors:
        raise ResolutionError("invalid adapter catalog: " + "; ".join(errors))

    task = load_structured_file(task_path)
    resolved_at = args.now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    resolution = resolve_dispatch(task.get("dispatch", {}), adapters, resolved_at)
    if args.write:
        if task.get("schema_version") == "4":
            runtime_path = runtime_file_for(task_path, task, None)
            if runtime_path is None:
                raise ResolutionError("Task v4 requires runtime_file before resolution can be written")
            if runtime_path.exists():
                runtime = load_structured_file(runtime_path)
            else:
                runtime = {
                    "schema_version": "1",
                    "task_id": task.get("id"),
                    "task_schema_version": "4",
                    "resolution": None,
                    "selected_at": None,
                    "heartbeat": None,
                    "resources": {"locks": []},
                    "runs": [],
                    "event_log_file": "events.jsonl",
                    "last_updated": resolved_at,
                }
            runtime["resolution"] = resolution
            runtime["selected_at"] = resolved_at
            runtime["last_updated"] = resolved_at
            runtime_schema = load_structured_file(schema_dir / "runtime.schema.json")
            runtime_errors = validate_schema(
                runtime, runtime_schema, str(runtime_path), runtime_schema
            )
            if runtime_errors:
                raise ResolutionError("invalid Runtime output: " + "; ".join(runtime_errors))
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            event_path = runtime_path.parent / runtime["event_log_file"]
            if not event_path.exists():
                event_path.write_text("", encoding="utf-8")
            runtime_path.write_text(
                json.dumps(runtime, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            task["dispatch"]["resolution"] = resolution
            task["dispatch"]["selected_at"] = resolved_at
            task_path.write_text(
                json.dumps(task, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    print(json.dumps(resolution, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, ResolutionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

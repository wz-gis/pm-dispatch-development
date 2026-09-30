#!/usr/bin/env python3
"""Select a Codex execution transport from a live tool inventory, without spawning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


TOOL_SETS = {
    "codex": ("create_thread", "send_message_to_thread", "wait_threads", "read_thread",
              "set_thread_archived", "automation_update"),
    "codex-subagent": ("spawn_agent", "send_input"),
}

AGENT_ROLES = {
    "create": ("spawn_agent",),
    "send": ("send_input", "followup_task", "send_message"),
    "wait": ("wait_agent",),
    "cancel": ("close_agent",),
    "interrupt": ("interrupt_agent",),
}
ROLE_INPUTS = {"create": {"prompt"}, "send": {"worker_id", "prompt"},
               "wait": {"worker_id", "timeout_ms"}, "cancel": {"worker_id"},
               "interrupt": {"worker_id"}}
DEFAULT_INPUTS = {
    "spawn_agent": {"prompt": "message"},
    "send_input": {"worker_id": "target", "prompt": "message", "interrupt": "interrupt"},
    "wait_agent": {"worker_id": "targets", "timeout_ms": "timeout_ms"},
    "close_agent": {"worker_id": "target"},
}


def inventory_names(inventory: list[str] | dict) -> list[str]:
    return inventory.get("tools", []) if isinstance(inventory, dict) else inventory


def tool_bindings(inventory: list[str] | dict) -> dict[str, str]:
    names = inventory_names(inventory)
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("tool inventory must be a JSON array of exact tool names")
    bindings = {}
    for name in names:
        leaf = name.rsplit("__", 1)[-1].rsplit(".", 1)[-1]
        bindings.setdefault(leaf, name)
    return bindings


def native_bindings(inventory: list[str] | dict) -> tuple[dict, list[str]]:
    """Bind roles, keeping unverified alternatives distinct from absent capabilities."""
    names = tool_bindings(inventory)
    overrides = inventory.get("native_agent_bindings", {}) if isinstance(inventory, dict) else {}
    if not isinstance(overrides, dict) or set(overrides) - set(AGENT_ROLES):
        raise ValueError("native_agent_bindings contains unknown operation roles")
    result, issues = {}, []
    for role, candidates in AGENT_ROLES.items():
        override = overrides.get(role)
        if override is not None:
            if not isinstance(override, dict) or override.get("schema_verified") is not True:
                raise ValueError(f"{role} binding requires schema_verified=true from live declarations")
            target = override.get("tool")
            if target not in inventory_names(inventory):
                raise ValueError(f"{role} binding tool is not in the live inventory")
            leaf = target.rsplit("__", 1)[-1].rsplit(".", 1)[-1]
            if role == "cancel" and leaf == "interrupt_agent":
                raise ValueError(f"{role} binding cannot use {leaf}; interrupt is not close")
            fields = override.get("input_map")
            allowed = ROLE_INPUTS[role] | ({"interrupt"} if role == "send" else set())
            if (not isinstance(fields, dict) or not ROLE_INPUTS[role].issubset(fields)
                    or set(fields) - allowed or any(not isinstance(v, str) or not v.isidentifier() for v in fields.values())
                    or len(set(fields.values())) != len(fields)):
                raise ValueError(f"{role} binding requires distinct native fields for {sorted(ROLE_INPUTS[role])}")
            list_inputs = override.get("list_inputs", [])
            if not isinstance(list_inputs, list) or any(field != "worker_id" for field in list_inputs):
                raise ValueError("only worker_id may be wrapped as a native ID list")
            paths = override.get("result_paths", {})
            if not isinstance(paths, dict) or set(paths) - {"worker_id", "submission_id", "status", "timed_out", "previous_status"}:
                raise ValueError("unsupported native result_paths")
            if any(not isinstance(path, str) or not path.startswith("$.") for path in paths.values()):
                raise ValueError("native result_paths must use $. paths")
            result[role] = {"tool": target, "input_map": fields, "list_inputs": list_inputs,
                            "result_paths": paths}
            continue
        leaf = next((candidate for candidate in candidates if candidate in names), None)
        if leaf in DEFAULT_INPUTS:
            result[role] = {"tool": names[leaf], "input_map": DEFAULT_INPUTS[leaf],
                            "list_inputs": ["worker_id"] if role == "wait" else [], "result_paths": {}}
        elif leaf:
            result[role] = {"tool": names[leaf], "needs_schema_binding": True}
            if role in {"create", "send"}:
                issues.append(f"{role}:bind-host-tools:{leaf}")
        elif role in {"create", "send"}:
            issues.append(f"{role}:missing-capability")
    return result, issues


def missing_tools(provider: str, names: list[str] | dict, required_capabilities: list[str] | None = None) -> list[str]:
    if provider == "codex-subagent":
        bindings, issues = native_bindings(names)
        if "terminal-event-wait" in (required_capabilities or []) and ("wait" not in bindings or bindings["wait"].get("needs_schema_binding")):
            issues.append("wait:missing-required-terminal-event-wait")
        return issues
    bindings = tool_bindings(names)
    return [name for name in TOOL_SETS.get(provider, ()) if name not in bindings]


def select_execution(names: list[str] | dict, *, require_visible: bool = False,
                     completion_notifications: bool = False) -> dict:
    bindings = tool_bindings(names)
    candidates = ["codex"] if require_visible else ["codex-subagent", "codex"]
    failures = {}
    for provider in candidates:
        missing = missing_tools(provider, names)
        if provider == "codex-subagent" and not completion_notifications:
            missing.append("verified-parent-completion-notifications")
        internal = provider == "codex-subagent"
        pending_binding = internal and completion_notifications and missing and all("bind-host-tools" in issue for issue in missing)
        if missing and not pending_binding:
            failures[provider] = missing
            continue
        operations = native_bindings(names)[0] if internal else {}
        return {
            "provider": provider,
            "worker_type": "codex-subagent" if internal else "codex-thread",
            "visibility": "internal" if internal else "user-visible",
            "monitor_mode": "milestone" if internal else "heartbeat",
            "heartbeat_required": not internal,
            "tools": ({role: operation["tool"] for role, operation in operations.items()} if internal
                      else {key: bindings[key] for key in TOOL_SETS[provider]}),
            "action": "bind-host-tools" if pending_binding else "ready",
            "binding_issues": missing,
            "optional_operations": {role: role in operations and not operations[role].get("needs_schema_binding", False)
                                    for role in ("wait", "cancel", "interrupt")} if internal else {},
            "authorization": "check actual host restrictions before creating a Worker",
        }
    return {"provider": None, "action": "unavailable" if require_visible else "direct",
            "missing": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", required=True, help="JSON tool-name array or host binding object")
    parser.add_argument("--require-visible", action="store_true")
    parser.add_argument("--completion-notifications", action="store_true")
    args = parser.parse_args()
    result = select_execution(json.loads(Path(args.tools).read_text()),
                              require_visible=args.require_visible,
                              completion_notifications=args.completion_notifications)
    print(json.dumps(result, indent=2))
    return 1 if result.get("action") == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())

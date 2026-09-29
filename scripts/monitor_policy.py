#!/usr/bin/env python3
"""Shared incremental-inspection policy constants and helpers."""

from __future__ import annotations

from typing import Any


CODEX_INSPECTION_POLICY_ADAPTER_VERSION = 13
INSPECTION_POLICY_NAME = "incremental-debounce"
INSPECTION_MIN_INTERVAL_SECONDS = 600
INSPECTION_MAX_CALLS_PER_CYCLE = 1
PROVISIONING_DEFAULT_TTL_SECONDS = 120
PROVISIONING_MAX_TTL_SECONDS = 300


def pending_inspection_authorizations(
    events: list[dict[str, Any]], run_id: str
) -> list[dict[str, Any]]:
    """Return status snapshot permits that have no persisted observation."""
    authorizations = [
        event
        for event in events
        if event.get("event_type") == "status-inspect-authorized"
        and event.get("run_id") == run_id
    ]
    observed = {
        str((event.get("payload") or {}).get("authorization_event_id") or "")
        for event in events
        if event.get("event_type") == "status-observed"
        and event.get("run_id") == run_id
    }
    return [
        event for event in authorizations if str(event.get("event_id") or "") not in observed
    ]


def inspection_policy_applies(run: dict[str, Any]) -> bool:
    if run.get("provider") != "codex":
        return False
    try:
        return int(str(run.get("adapter_version") or "0")) >= CODEX_INSPECTION_POLICY_ADAPTER_VERSION
    except ValueError:
        return False


def new_inspection_budget(enforced_at: str) -> dict[str, Any]:
    return {
        "policy": INSPECTION_POLICY_NAME,
        "min_interval_seconds": INSPECTION_MIN_INTERVAL_SECONDS,
        "max_calls_per_cycle": INSPECTION_MAX_CALLS_PER_CYCLE,
        "enforced_at": enforced_at,
    }

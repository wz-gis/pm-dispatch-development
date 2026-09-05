#!/usr/bin/env python3
"""Shared Codex terminal-wait policy constants and helpers."""

from __future__ import annotations

from typing import Any


CODEX_WAIT_POLICY_ADAPTER_VERSION = 12
CODEX_WAIT_POLICY_NAME = "single-short"
CODEX_WAIT_MAX_CALLS_PER_RUN = 1
CODEX_WAIT_MAX_TIMEOUT_MS = 30_000


def codex_wait_policy_applies(run: dict[str, Any]) -> bool:
    if run.get("provider") != "codex":
        return False
    try:
        return int(str(run.get("adapter_version") or "0")) >= CODEX_WAIT_POLICY_ADAPTER_VERSION
    except ValueError:
        return False


def new_wait_budget(enforced_at: str) -> dict[str, Any]:
    return {
        "policy": CODEX_WAIT_POLICY_NAME,
        "max_calls": CODEX_WAIT_MAX_CALLS_PER_RUN,
        "max_timeout_ms": CODEX_WAIT_MAX_TIMEOUT_MS,
        "enforced_at": enforced_at,
    }

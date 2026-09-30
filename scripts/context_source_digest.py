#!/usr/bin/env python3
"""Compute stable identities for Context Packet sources."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


RAW_FILE_V1 = "raw-file-v1"
RUNTIME_CONTEXT_V1 = "runtime-context-v1"
EVIDENCE_DIGEST_V1 = "evidence-digest-v1"
PROJECT_SNAPSHOT_V1 = "project-snapshot-v1"
SOURCE_DIGEST_KINDS = {
    RAW_FILE_V1,
    RUNTIME_CONTEXT_V1,
    EVIDENCE_DIGEST_V1,
    PROJECT_SNAPSHOT_V1,
}
ACTIVE_EXECUTION_STATUSES = {"provisioning", "queued", "running"}


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _select_execution(values: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [value for value in values if isinstance(value, dict)]
    active = [
        value for value in valid if value.get("status") in ACTIVE_EXECUTION_STATUSES
    ]
    return (active or valid)[-1] if valid else None


def _pick(value: dict[str, Any] | None, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {field: copy.deepcopy(value.get(field)) for field in fields}


def runtime_context_projection(runtime: dict[str, Any]) -> dict[str, Any]:
    """Keep only Runtime state that can change a Worker's next decision."""
    run = _select_execution(runtime.get("runs") or [])
    attempt = _select_execution((run or {}).get("attempts") or [])
    lease = (attempt or {}).get("lease")
    resolution = _pick(
        runtime.get("resolution"),
        (
            "provider",
            "adapter_version",
            "model_id",
            "reasoning_profile",
            "provider_reasoning_effort",
            "worker_type",
            "monitor_mode",
            "capabilities",
            "evidence_kinds",
        ),
    )
    heartbeat = _pick(
        runtime.get("heartbeat"),
        (
            "automation_id",
            "coordinator_thread_id",
            "coordinator_epoch",
            "target_run_id",
            "scan_scope",
            "read_set",
            "interval_minutes",
            "status",
        ),
    )
    run_projection = _pick(
        run,
        (
            "run_id",
            "gate",
            "worker_type",
            "worker_id",
            "provider",
            "adapter_version",
            "model_id",
            "reasoning_profile",
            "provider_reasoning_effort",
            "design_fingerprint",
            "status",
        ),
    )
    if run_projection is not None:
        observation = (run or {}).get("observation")
        if observation:
            run_projection["observation"] = _pick(
                observation, ("provider_status", "state", "reason", "command_id", "command_deadline")
            )
        run_projection["attempt"] = _pick(
            attempt,
            ("attempt_id", "status", "commit", "evidence_ref"),
        )
        run_projection["milestone"] = _pick(
            lease,
            (
                "progress_seq",
                "last_progress_at",
                "last_progress_summary",
                "liveness_state",
                "monitor_gap_started_at",
            ),
        )
    locks = [
        _pick(lock, ("resource_id", "type", "mode", "holder_run_id", "status", "scope"))
        for lock in runtime.get("resources", {}).get("locks", [])
        if isinstance(lock, dict) and lock.get("status") == "active"
    ]
    locks.sort(
        key=lambda lock: (
            str((lock or {}).get("resource_id") or ""),
            str((lock or {}).get("holder_run_id") or ""),
        )
    )
    return {
        "schema_version": runtime.get("schema_version"),
        "task_id": runtime.get("task_id"),
        "task_schema_version": runtime.get("task_schema_version"),
        "resolution": resolution,
        "heartbeat": heartbeat,
        "execution": run_projection,
        "active_locks": locks,
    }


def evidence_digest_identity(document: dict[str, Any]) -> str:
    payload = copy.deepcopy(document)
    payload.pop("generated_at", None)
    payload.pop("digest_sha256", None)
    source = payload.get("source_digest")
    if isinstance(source, dict):
        source.pop("path", None)
    return canonical_sha256(payload)


def project_snapshot_identity(document: dict[str, Any]) -> str:
    payload = copy.deepcopy(document)
    payload.pop("generated_at", None)
    payload.pop("snapshot_sha256", None)
    payload.pop("root", None)
    return canonical_sha256(payload)


def source_sha256(
    path: Path, digest_kind: str, document: dict[str, Any] | None = None
) -> str:
    if digest_kind == RAW_FILE_V1:
        return file_sha256(path)
    if document is None:
        document = json.loads(path.read_text(encoding="utf-8"))
    if digest_kind == RUNTIME_CONTEXT_V1:
        return canonical_sha256(runtime_context_projection(document))
    if digest_kind == EVIDENCE_DIGEST_V1:
        return evidence_digest_identity(document)
    if digest_kind == PROJECT_SNAPSHOT_V1:
        return project_snapshot_identity(document)
    raise ValueError(f"unsupported source digest kind {digest_kind!r}")

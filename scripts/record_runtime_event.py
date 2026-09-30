#!/usr/bin/env python3
"""Validate and append one immutable Runtime event."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_structured_file,
    parse_time,
    runtime_file_for,
    validate_schema,
)


class RuntimeEventError(ValueError):
    """Raised when an event cannot be appended without corrupting history."""


def resolve_runtime_path(path: Path) -> Path:
    document = load_structured_file(path)
    if document.get("schema_version") == "4" and "dispatch" in document:
        resolved = runtime_file_for(path, document, None)
        if resolved is None or not resolved.exists():
            raise RuntimeEventError("Task v4 Runtime sidecar is missing")
        return resolved
    if document.get("schema_version") == "1" and "task_schema_version" in document:
        return path
    raise RuntimeEventError("expected Task v4 or Runtime v1")


def append_event(
    runtime_path: Path,
    event: dict[str, Any],
    event_schema: dict[str, Any],
    write: bool,
) -> Path:
    runtime = load_structured_file(runtime_path)
    errors = validate_schema(event, event_schema, "event", event_schema)
    if errors:
        raise RuntimeEventError("; ".join(errors))
    if event.get("task_id") != runtime.get("task_id"):
        raise RuntimeEventError("event task_id does not match Runtime task_id")
    configured_value = str(runtime.get("event_log_file") or "").strip()
    if not configured_value:
        raise RuntimeEventError("Runtime requires event_log_file")
    event_path = Path(configured_value)
    if not event_path.is_absolute():
        event_path = (runtime_path.parent / event_path).resolve()
    if not event_path.exists():
        raise RuntimeEventError(f"event log does not exist: {event_path}")

    with event_path.open("r+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        stream.seek(0)
        last_time: datetime | None = None
        for lineno, line in enumerate(stream.read().splitlines(), 1):
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeEventError(f"existing event {lineno} is invalid: {exc}") from exc
            if existing.get("event_id") == event.get("event_id"):
                raise RuntimeEventError(f"duplicate event_id {event.get('event_id')!r}")
            last_time = parse_time(existing.get("occurred_at"))
        event_time = parse_time(event.get("occurred_at"))
        if last_time and event_time < last_time:
            raise RuntimeEventError("event occurred_at is earlier than the current log tail")

        if write:
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return event_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and append one Runtime event.")
    parser.add_argument("document", help="Path to Task v4 or Runtime v1")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--provider")
    parser.add_argument("--worker-id")
    parser.add_argument("--payload", default="{}", help="JSON object")
    parser.add_argument("--now", help="Event timestamp; defaults to current UTC")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.document).resolve()
    runtime_path = resolve_runtime_path(input_path)
    runtime = load_structured_file(runtime_path)
    occurred_at = args.now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = json.loads(args.payload)
    if not isinstance(payload, dict):
        raise RuntimeEventError("payload must be a JSON object")
    event = {
        "schema_version": "1",
        "event_id": args.event_id,
        "event_type": args.event_type,
        "task_id": runtime.get("task_id"),
        "occurred_at": occurred_at,
        "run_id": args.run_id,
        "attempt_id": args.attempt_id,
        "provider": args.provider,
        "worker_id": args.worker_id,
        "payload": payload,
    }
    schema_path = SCRIPT_DIR.parent / "references" / "schemas" / "runtime-event.schema.json"
    event_schema = load_structured_file(schema_path)
    assert_supported_schema(event_schema, str(schema_path))
    event_path = append_event(runtime_path, event, event_schema, args.write)
    print(
        json.dumps(
            {"event": event, "event_log": str(event_path), "written": args.write},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeEventError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

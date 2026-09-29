#!/usr/bin/env python3
"""Report advisory context usage without changing coordinator ownership."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


WARN_INPUT_TOKENS = 96_000
ROLLOVER_INPUT_TOKENS = 160_000
MAX_MODEL_STEPS = 150


def utc_now(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def codex_thread_id(value: str) -> str:
    return value.removeprefix("codex-thread:")


def find_session(session_dir: Path, thread_id: str) -> Path | None:
    if session_dir.is_file():
        return session_dir
    if not session_dir.is_dir():
        return None
    matches = sorted(session_dir.rglob(f"*{codex_thread_id(thread_id)}*.jsonl"))
    return matches[-1] if matches else None


def token_records(lines: Iterable[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in lines:
        if '"token_count"' not in line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = record.get("payload") or {}
        info = payload.get("info") or {}
        if payload.get("type") != "token_count" or not isinstance(info, dict):
            continue
        records.append(info)
    return records


def assess_usage(
    *,
    last_input_tokens: int,
    model_steps: int,
    warn_input_tokens: int = WARN_INPUT_TOKENS,
    rollover_input_tokens: int = ROLLOVER_INPUT_TOKENS,
    max_model_steps: int = MAX_MODEL_STEPS,
) -> tuple[str, list[str]]:
    # Retain legacy arguments for callers; lifetime record counts do not measure
    # current context pressure, and neither threshold authorizes a handoff.
    if last_input_tokens >= warn_input_tokens:
        return "warn", [f"last input {last_input_tokens} >= warning {warn_input_tokens}"]
    return "continue", []


def build_report(
    session_path: Path | None,
    *,
    thread_id: str,
    epoch: int = 1,
    measured_at: str | None = None,
    warn_input_tokens: int = WARN_INPUT_TOKENS,
    rollover_input_tokens: int = ROLLOVER_INPUT_TOKENS,
    max_model_steps: int = MAX_MODEL_STEPS,
) -> dict[str, Any]:
    budget = {
        "warn_input_tokens": warn_input_tokens,
        "rollover_input_tokens": rollover_input_tokens,
        "max_model_steps": max_model_steps,
    }
    if session_path is None or not session_path.is_file():
        return {
            "schema_version": "1",
            "thread_id": thread_id,
            "epoch": epoch,
            "session_file": None,
            "usage": None,
            "budget": budget,
            "action": "unknown",
            "reasons": ["coordinator session log unavailable"],
            "measured_at": utc_now(measured_at),
        }
    records = token_records(session_path.read_text(encoding="utf-8").splitlines())
    if not records:
        return {
            "schema_version": "1",
            "thread_id": thread_id,
            "epoch": epoch,
            "session_file": str(session_path.resolve()),
            "usage": None,
            "budget": budget,
            "action": "unknown",
            "reasons": ["session log has no token_count records"],
            "measured_at": utc_now(measured_at),
        }
    latest = records[-1]
    total = latest.get("total_token_usage") or {}
    last = latest.get("last_token_usage") or {}
    last_input = int(last.get("input_tokens") or 0)
    steps = len(records)
    action, reasons = assess_usage(
        last_input_tokens=last_input,
        model_steps=steps,
        warn_input_tokens=warn_input_tokens,
        rollover_input_tokens=rollover_input_tokens,
        max_model_steps=max_model_steps,
    )
    return {
        "schema_version": "1",
        "thread_id": thread_id,
        "epoch": epoch,
        "session_file": str(session_path.resolve()),
        "usage": {
            "last_input_tokens": last_input,
            "model_steps": steps,
            "model_context_window": int(latest.get("model_context_window") or 0),
            "total_input_tokens": int(total.get("input_tokens") or 0),
            "cached_input_tokens": int(total.get("cached_input_tokens") or 0),
        },
        "budget": budget,
        "action": action,
        "reasons": reasons,
        "measured_at": utc_now(measured_at),
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a PM coordinator context budget.")
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--epoch", type=int, default=1)
    parser.add_argument("--session")
    parser.add_argument("--session-dir")
    parser.add_argument("--output")
    parser.add_argument("--warn-input-tokens", type=int, default=WARN_INPUT_TOKENS)
    parser.add_argument(
        "--rollover-input-tokens", type=int, default=ROLLOVER_INPUT_TOKENS
    )
    parser.add_argument("--max-model-steps", type=int, default=MAX_MODEL_STEPS)
    parser.add_argument("--now")
    args = parser.parse_args()
    if args.epoch < 1:
        parser.error("--epoch must be at least 1")
    if not 0 < args.warn_input_tokens < args.rollover_input_tokens:
        parser.error("input token thresholds must satisfy 0 < warn < rollover")
    if args.max_model_steps < 1:
        parser.error("--max-model-steps must be at least 1")
    session_path = Path(args.session).resolve() if args.session else None
    if session_path is None:
        session_dir = (
            Path(args.session_dir).resolve()
            if args.session_dir
            else Path.home() / ".codex" / "sessions"
        )
        session_path = find_session(session_dir, args.thread_id)
    report = build_report(
        session_path,
        thread_id=args.thread_id,
        epoch=args.epoch,
        measured_at=args.now,
        warn_input_tokens=args.warn_input_tokens,
        rollover_input_tokens=args.rollover_input_tokens,
        max_model_steps=args.max_model_steps,
    )
    if args.output:
        atomic_write(Path(args.output).resolve(), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

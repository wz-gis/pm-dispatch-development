#!/usr/bin/env python3
"""Run the compact, deterministic preflight before dispatching a Worker."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_context_packet import build_context_packet  # noqa: E402
from build_evidence_digest import build_evidence_digest  # noqa: E402
from build_project_snapshot import build_project_snapshot  # noqa: E402
from manage_recovery_ledger import (  # noqa: E402
    default_path,
    initial_ledger,
    validate_ledger,
)
from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_structured_file,
    validate_schema,
)


def now_iso(value: str | None) -> str:
    return value or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run_preflight(
    task_path: Path,
    *,
    project_root: Path,
    output_dir: Path,
    gate: str | None,
    focus: list[str],
    verification_commands: list[str],
    max_chars: int,
    max_files: int,
    generated_at: str | None,
) -> dict[str, str | None]:
    task_path = task_path.resolve()
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_iso(generated_at)
    evidence_path = task_path.parent / "evidence.yaml"
    task = load_structured_file(task_path)
    configured_evidence = task.get("verification", {}).get("evidence_file")
    if configured_evidence:
        candidate = Path(str(configured_evidence))
        evidence_path = candidate if candidate.is_absolute() else task_path.parent / candidate

    digest_path = output_dir / "current-evidence.json"
    digest_result: str | None = None
    if evidence_path.is_file():
        digest, digest_text = build_evidence_digest(
            task_path, digest_path, max_chars=max_chars, generated_at=stamp
        )
        write_json(digest_path, digest)
        digest_result = digest["digest_sha256"]
        if len(digest_text) > max_chars:
            raise ValueError(f"Evidence Digest exceeds {max_chars} chars")

    snapshot_path = output_dir / "project-snapshot.json"
    snapshot, snapshot_text = build_project_snapshot(
        project_root,
        snapshot_path,
        focus=focus,
        max_files=max_files,
        max_chars=max_chars,
        generated_at=stamp,
    )
    write_json(snapshot_path, snapshot)
    if len(snapshot_text) > max_chars:
        raise ValueError(f"Project Snapshot exceeds {max_chars} chars")

    ledger_path = output_dir / "recovery-ledger.json"
    if ledger_path.exists():
        ledger = load_structured_file(ledger_path)
    else:
        ledger = initial_ledger(task["id"], stamp)
        write_json(ledger_path, ledger)
    schema_dir = SCRIPT_DIR.parent / "references" / "schemas"
    ledger_errors = validate_ledger(ledger, ledger_path, schema_dir)
    if ledger_errors:
        raise ValueError("invalid Recovery Ledger:\n" + "\n".join(ledger_errors))

    packet_path = output_dir / "active-context.json"
    packet, packet_text = build_context_packet(
        task_path,
        packet_path,
        mode="initial",
        gate=gate,
        verification_commands=verification_commands,
        packet_max_chars=max_chars,
        evidence_digest_path=digest_path if digest_path.exists() else None,
        project_snapshot_path=snapshot_path,
        recovery_ledger_path=ledger_path,
        generated_at=stamp,
    )
    write_json(packet_path, packet)
    if len(packet_text) > max_chars:
        raise ValueError(f"Context Packet exceeds {max_chars} chars")

    return {
        "task_id": str(task["id"]),
        "evidence_digest": digest_result,
        "project_snapshot": snapshot["snapshot_sha256"],
        "context_packet": packet["packet_sha256"],
        "output_dir": str(output_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the compact PM dispatch preflight bundle.")
    parser.add_argument("task")
    parser.add_argument("--project-root")
    parser.add_argument("--output-dir")
    parser.add_argument("--gate", choices=["contract", "implementation", "integration", "verification", "closure"])
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--verification-command", action="append", default=[])
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument("--now")
    args = parser.parse_args()
    task_path = Path(args.task).resolve()
    project_root = (
        Path(args.project_root).resolve()
        if args.project_root
        else task_path.parents[3]
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else Path("/tmp/pm-dispatch") / task_path.parent.name
    )
    result = run_preflight(
        task_path,
        project_root=project_root,
        output_dir=output_dir,
        gate=args.gate,
        focus=args.focus,
        verification_commands=args.verification_command,
        max_chars=args.max_chars,
        max_files=args.max_files,
        generated_at=args.now,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

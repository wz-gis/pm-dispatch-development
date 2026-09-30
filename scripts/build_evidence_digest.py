#!/usr/bin/env python3
"""Build a bounded current-state digest from full Evidence v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_evidence_digest import (  # noqa: E402
    digest_sha256,
    validate_evidence_digest,
)
from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    evidence_file_for,
    load_structured_file,
    validate_schema,
)


ACTIVE_RUN_STATUSES = {"queued", "running"}


def compact(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def unique_text(values: list[Any], limit: int, count: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = compact(value, limit)
        if text and text not in result:
            result.append(text)
        if len(result) >= count:
            break
    return result


def source_digest(source: Path, output: Path) -> dict[str, str]:
    return {
        "path": os.path.relpath(source.resolve(), output.parent.resolve()),
        "sha256": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def select_current_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    active = [run for run in runs if run.get("status") in ACTIVE_RUN_STATUSES]
    return (active or runs)[-1] if runs else None


def collect_artifacts(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    artifacts = evidence.get("artifacts", {})
    for kind, values in artifacts.items():
        if kind in {"commits", "files_changed"} or not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict) or not item.get("artifact_id"):
                continue
            result.append(
                {
                    "artifact_id": str(item["artifact_id"]),
                    "kind": str(item.get("kind") or kind),
                    "result": str(item.get("result") or "info"),
                    "evidence_ref": str(item.get("evidence_ref") or "missing"),
                    "digest": item.get("digest"),
                }
            )
    return result


def build_evidence_digest(
    task_path: Path,
    output_path: Path,
    *,
    max_chars: int = 6000,
    generated_at: str | None = None,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], str]:
    task_path = task_path.resolve()
    output_path = output_path.resolve()
    schema_dir = schema_dir or SCRIPT_DIR.parent / "references" / "schemas"
    task_schema = load_structured_file(schema_dir / "task.schema.json")
    evidence_schema = load_structured_file(schema_dir / "evidence.schema.json")
    digest_schema = load_structured_file(schema_dir / "evidence-digest.schema.json")
    for name, schema in (
        ("task.schema.json", task_schema),
        ("evidence.schema.json", evidence_schema),
        ("evidence-digest.schema.json", digest_schema),
    ):
        assert_supported_schema(schema, name)
    task = load_structured_file(task_path)
    errors = validate_schema(task, task_schema, str(task_path), task_schema)
    evidence_path = evidence_file_for(task_path, task, None)
    if not evidence_path.is_file():
        raise ValueError(f"Evidence source is missing: {evidence_path}")
    evidence = load_structured_file(evidence_path)
    errors.extend(
        validate_schema(evidence, evidence_schema, str(evidence_path), evidence_schema)
    )
    if errors:
        raise ValueError("invalid PM sources:\n" + "\n".join(errors))

    levels = evidence.get("verification", {}).get("levels", {})
    facts: list[dict[str, Any]] = []
    for level in ("L4", "L3", "L2", "L1", "L0"):
        item = levels.get(level) or {}
        if item.get("status") not in {"pass", "pass_mock"}:
            continue
        summary = compact(item.get("summary"), 300)
        if summary:
            facts.append(
                {
                    "claim": f"{level}: {summary}",
                    "status": item["status"],
                    "artifact_ids": unique_text(
                        list(item.get("evidence_refs", [])), 120, 6
                    ),
                }
            )

    quality_checks = []
    for check in evidence.get("quality_checks", []):
        if not isinstance(check, dict):
            continue
        quality_checks.append(
            {
                "id": str(check.get("id") or "unknown"),
                "status": str(check.get("status") or "pending"),
                "summary": compact(check.get("summary"), 260),
                "evidence_refs": unique_text(
                    list(check.get("evidence_refs", [])), 120, 6
                ),
                "checked_at": check.get("checked_at"),
            }
        )

    runs = [run for run in evidence.get("runs", []) if isinstance(run, dict)]
    current = select_current_run(runs)
    recent_runs = [
        {
            "run_id": str(run.get("run_id") or "unknown-run"),
            "attempt_id": str(run.get("attempt_id") or "unknown-attempt"),
            "status": str(run.get("status") or "unknown"),
            "commit": run.get("commit"),
        }
        for run in runs[-5:]
    ]
    conclusion = evidence.get("conclusion", {})
    digest: dict[str, Any] = {
        "schema_version": "1",
        "derived": True,
        "task_id": evidence["task_id"],
        "current_state": {
            "conclusion_status": str(conclusion.get("status") or "PARTIAL_VERIFIED"),
            "evidence_level": str(conclusion.get("evidence_level") or "NONE"),
            "real_chain_verified": conclusion.get("real_chain_verified") is True,
            "changed_surface": unique_text(
                list(evidence.get("verification", {}).get("changed_surface", [])),
                180,
                12,
            ),
            "uncovered_items": unique_text(
                list(evidence.get("verification", {}).get("uncovered_items", [])),
                260,
                10,
            ),
            "run_id": current.get("run_id") if current else None,
            "attempt_id": current.get("attempt_id") if current else None,
            "run_status": current.get("status") if current else None,
        },
        "confirmed_facts": facts[:8],
        "quality_checks": quality_checks[:12],
        "artifact_index": collect_artifacts(evidence)[:24],
        "open_blockers": [
            {
                "id": str(item.get("id") or "unknown"),
                "type": str(item.get("type") or "unknown"),
                "description": compact(item.get("description"), 300),
            }
            for item in evidence.get("blockers", [])
            if isinstance(item, dict) and item.get("status") == "open"
        ][:6],
        "audit": {
            "run_count": len(runs),
            "omitted_run_count": max(0, len(runs) - len(recent_runs)),
            "recent_runs": recent_runs,
        },
        "budget": {"max_chars": max_chars},
        "source_digest": source_digest(evidence_path, output_path),
        "generated_at": generated_at
        or datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "digest_sha256": "",
    }
    digest["digest_sha256"] = digest_sha256(digest)
    rendered = json.dumps(digest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(rendered) > max_chars:
        digest["artifact_index"] = digest["artifact_index"][:8]
        digest["quality_checks"] = digest["quality_checks"][:8]
        digest["confirmed_facts"] = digest["confirmed_facts"][:5]
        digest["audit"]["recent_runs"] = digest["audit"]["recent_runs"][-3:]
        digest["audit"]["omitted_run_count"] = max(
            0, len(runs) - len(digest["audit"]["recent_runs"])
        )
        digest["digest_sha256"] = digest_sha256(digest)
        rendered = json.dumps(digest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    validation_errors = validate_evidence_digest(
        digest,
        digest_path=output_path,
        schema=digest_schema,
        rendered=rendered,
        check_source=True,
    )
    if validation_errors:
        raise ValueError("invalid Evidence Digest:\n" + "\n".join(validation_errors))
    return digest, rendered


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one bounded Evidence Digest.")
    parser.add_argument("task")
    parser.add_argument("--output")
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--now")
    args = parser.parse_args()
    task_path = Path(args.task).resolve()
    output_path = (
        Path(args.output).resolve()
        if args.output
        else task_path.parent / "context" / "current-evidence.json"
    )
    digest, rendered = build_evidence_digest(
        task_path,
        output_path,
        max_chars=args.max_chars,
        generated_at=args.now,
    )
    atomic_write(output_path, rendered)
    print(f"Wrote {output_path}")
    print(digest["digest_sha256"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

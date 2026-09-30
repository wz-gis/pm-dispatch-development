#!/usr/bin/env python3
"""Build and validate a bounded deterministic project snapshot."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    load_structured_file,
    validate_schema,
)


DEFAULT_EXCLUDES = {
    ".git",
    ".next",
    ".venv",
    ".artifacts",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def canonical_payload(snapshot: dict[str, Any]) -> bytes:
    payload = copy.deepcopy(snapshot)
    payload.pop("generated_at", None)
    payload.pop("snapshot_sha256", None)
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_payload(snapshot)).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def run_git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def git_snapshot(root: Path) -> tuple[dict[str, Any], str | None]:
    head = run_git(root, "rev-parse", "HEAD")
    status = run_git(root, "status", "--porcelain=v1", "-z")
    branch = run_git(root, "branch", "--show-current")
    if head is None or status is None:
        return {
            "available": False,
            "head": None,
            "branch": None,
            "dirty_paths": [],
            "omitted_dirty_paths": 0,
            "status_sha256": None,
        }, None
    entries = [item for item in status.split("\0") if item]
    paths = []
    for entry in entries:
        path = entry[3:] if len(entry) > 3 else entry
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and path not in paths:
            paths.append(path)
    return {
        "available": True,
        "head": head.strip(),
        "branch": (branch or "").strip() or None,
        "dirty_paths": paths[:40],
        "omitted_dirty_paths": max(0, len(paths) - 40),
        "status_sha256": bytes_sha256(status.encode("utf-8")),
    }, status


def iter_project_files(root: Path, max_files: int):
    seen = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in DEFAULT_EXCLUDES)
        for name in sorted(files):
            path = Path(current) / name
            if path.is_symlink():
                continue
            yield path
            seen += 1
            if seen >= max_files:
                return


def focus_entry(root: Path, configured: str) -> dict[str, Any]:
    candidate = Path(configured)
    path = candidate if candidate.is_absolute() else (root / candidate)
    path = path.resolve()
    try:
        relative = os.path.relpath(path, root)
    except ValueError:
        relative = str(path)
    if not path.exists():
        return {
            "path": relative,
            "state": "missing",
            "size_bytes": None,
            "line_count": None,
            "sha256": None,
        }
    if path.is_dir():
        return {
            "path": relative,
            "state": "directory",
            "size_bytes": None,
            "line_count": None,
            "sha256": None,
        }
    data = path.read_bytes()
    return {
        "path": relative,
        "state": "file",
        "size_bytes": len(data),
        "line_count": data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
        "sha256": bytes_sha256(data),
    }


def validate_project_snapshot(
    snapshot: dict[str, Any],
    *,
    snapshot_path: Path,
    schema: dict[str, Any],
    rendered: str | None = None,
    check_sources: bool = True,
) -> list[str]:
    errors = validate_schema(snapshot, schema, str(snapshot_path), schema)
    if errors:
        return errors
    expected = snapshot_sha256(snapshot)
    if snapshot.get("snapshot_sha256") != expected:
        errors.append(f"{snapshot_path}: snapshot_sha256 mismatch; expected {expected}")
    if rendered is not None and len(rendered) > int(snapshot["budget"]["max_chars"]):
        errors.append(
            f"{snapshot_path}: snapshot has {len(rendered)} chars; maximum is "
            f"{snapshot['budget']['max_chars']}"
        )
    if not check_sources:
        return errors
    root = Path(snapshot["root"])
    if not root.is_dir():
        errors.append(f"{snapshot_path}: project root is missing: {root}")
        return errors
    current_git, _ = git_snapshot(root)
    recorded_git = snapshot["git"]
    for key in ("available", "head", "branch", "status_sha256"):
        if current_git.get(key) != recorded_git.get(key):
            errors.append(f"{snapshot_path}: git {key} drift")
    for entry in snapshot["focus"]:
        current = focus_entry(root, entry["path"])
        for key in ("state", "size_bytes", "line_count", "sha256"):
            if current.get(key) != entry.get(key):
                errors.append(f"{snapshot_path}: focus source drift for {entry['path']}")
                break
    return errors


def build_project_snapshot(
    root: Path,
    output_path: Path,
    *,
    focus: list[str] | None = None,
    max_files: int = 5000,
    max_chars: int = 6000,
    generated_at: str | None = None,
    schema_dir: Path | None = None,
) -> tuple[dict[str, Any], str]:
    root = root.resolve()
    output_path = output_path.resolve()
    schema_dir = schema_dir or SCRIPT_DIR.parent / "references" / "schemas"
    schema = load_structured_file(schema_dir / "project-snapshot.schema.json")
    assert_supported_schema(schema, "project-snapshot.schema.json")
    git_data, _ = git_snapshot(root)
    top_level: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    scanned = 0
    for path in iter_project_files(root, max_files):
        scanned += 1
        relative = path.relative_to(root)
        top_level[relative.parts[0]] += 1
        extensions[path.suffix.lower() or "<none>"] += 1
    truncated = scanned >= max_files
    snapshot: dict[str, Any] = {
        "schema_version": "1",
        "derived": True,
        "root": str(root),
        "git": git_data,
        "file_index": {
            "scanned_files": scanned,
            "truncated": truncated,
            "top_level_counts": dict(top_level.most_common(20)),
            "extension_counts": dict(extensions.most_common(20)),
        },
        "focus": [focus_entry(root, item) for item in (focus or [])[:20]],
        "budget": {"max_chars": max_chars, "max_files": max_files},
        "generated_at": generated_at
        or datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "snapshot_sha256": "",
    }
    snapshot["snapshot_sha256"] = snapshot_sha256(snapshot)
    rendered = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(rendered) > max_chars:
        snapshot["git"]["dirty_paths"] = snapshot["git"]["dirty_paths"][:12]
        snapshot["focus"] = snapshot["focus"][:10]
        snapshot["file_index"]["top_level_counts"] = dict(
            list(snapshot["file_index"]["top_level_counts"].items())[:10]
        )
        snapshot["file_index"]["extension_counts"] = dict(
            list(snapshot["file_index"]["extension_counts"].items())[:10]
        )
        snapshot["snapshot_sha256"] = snapshot_sha256(snapshot)
        rendered = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    errors = validate_project_snapshot(
        snapshot,
        snapshot_path=output_path,
        schema=schema,
        rendered=rendered,
        check_sources=True,
    )
    if errors:
        raise ValueError("invalid Project Snapshot:\n" + "\n".join(errors))
    return snapshot, rendered


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or validate a PM project snapshot.")
    parser.add_argument("root", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--now")
    parser.add_argument("--validate")
    parser.add_argument("--no-source-check", action="store_true")
    args = parser.parse_args()
    schema_path = SCRIPT_DIR.parent / "references" / "schemas" / "project-snapshot.schema.json"
    schema = load_structured_file(schema_path)
    assert_supported_schema(schema, str(schema_path))
    if args.validate:
        path = Path(args.validate).resolve()
        rendered = path.read_text(encoding="utf-8")
        snapshot = load_structured_file(path)
        errors = validate_project_snapshot(
            snapshot,
            snapshot_path=path,
            schema=schema,
            rendered=rendered,
            check_sources=not args.no_source_check,
        )
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("PM project snapshot validation passed.")
        return 0
    if not args.root:
        parser.error("root is required unless --validate is used")
    root = Path(args.root).resolve()
    output_path = (
        Path(args.output).resolve()
        if args.output
        else root / ".pm-dispatch" / "project-snapshot.json"
    )
    snapshot, rendered = build_project_snapshot(
        root,
        output_path,
        focus=args.focus,
        max_files=args.max_files,
        max_chars=args.max_chars,
        generated_at=args.now,
    )
    atomic_write(output_path, rendered)
    print(f"Wrote {output_path}")
    print(snapshot["snapshot_sha256"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

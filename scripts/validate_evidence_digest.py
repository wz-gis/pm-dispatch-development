#!/usr/bin/env python3
"""Validate a compact Evidence Digest and its source Evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
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


def canonical_payload(digest: dict[str, Any]) -> bytes:
    payload = copy.deepcopy(digest)
    payload.pop("generated_at", None)
    payload.pop("digest_sha256", None)
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest_sha256(digest: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_payload(digest)).hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_source(digest_path: Path, configured: str) -> Path:
    path = Path(configured)
    return path if path.is_absolute() else (digest_path.parent / path).resolve()


def validate_evidence_digest(
    digest: dict[str, Any],
    *,
    digest_path: Path,
    schema: dict[str, Any],
    rendered: str | None = None,
    check_source: bool = True,
) -> list[str]:
    errors = validate_schema(digest, schema, str(digest_path), schema)
    if errors:
        return errors
    expected = digest_sha256(digest)
    if digest.get("digest_sha256") != expected:
        errors.append(f"{digest_path}: digest_sha256 mismatch; expected {expected}")
    if rendered is not None and len(rendered) > int(digest["budget"]["max_chars"]):
        errors.append(
            f"{digest_path}: digest has {len(rendered)} chars; maximum is "
            f"{digest['budget']['max_chars']}"
        )
    if check_source:
        source = digest["source_digest"]
        source_path = resolve_source(digest_path, source["path"])
        if not source_path.is_file():
            errors.append(f"{digest_path}: Evidence source is missing: {source_path}")
        else:
            actual = file_sha256(source_path)
            if actual != source["sha256"]:
                errors.append(
                    f"{digest_path}: Evidence source digest drift; expected "
                    f"{source['sha256']}, got {actual}"
                )
            evidence = load_structured_file(source_path)
            if evidence.get("task_id") != digest.get("task_id"):
                errors.append(f"{digest_path}: task_id does not match Evidence source")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one PM Evidence Digest.")
    parser.add_argument("digest")
    parser.add_argument("--schema")
    parser.add_argument("--no-source-check", action="store_true")
    args = parser.parse_args()
    digest_path = Path(args.digest).resolve()
    schema_path = (
        Path(args.schema).resolve()
        if args.schema
        else SCRIPT_DIR.parent
        / "references"
        / "schemas"
        / "evidence-digest.schema.json"
    )
    rendered = digest_path.read_text(encoding="utf-8")
    digest = load_structured_file(digest_path)
    schema = load_structured_file(schema_path)
    assert_supported_schema(schema, str(schema_path))
    errors = validate_evidence_digest(
        digest,
        digest_path=digest_path,
        schema=schema,
        rendered=rendered,
        check_source=not args.no_source_check,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("PM Evidence Digest validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

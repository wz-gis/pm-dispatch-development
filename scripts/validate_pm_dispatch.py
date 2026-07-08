#!/usr/bin/env python3
"""Validate PM dispatch task/evidence files and enforce gate policy.

This script intentionally has no required third-party dependencies. If PyYAML is
installed it is used; otherwise a small YAML subset parser handles the templates
produced by this skill.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_RUN_STATUSES = {"queued", "running"}
ACTIVE_LOCK_STATUSES = {"active"}
VERIFIED_STATUSES = {
    "VERIFIED",
    "L0_VERIFIED_MOCK",
    "L1_VERIFIED_MOCK",
    "L2_VERIFIED_MOCK",
    "L3_VERIFIED_MOCK",
    "L4_VERIFIED_MOCK",
}
BLOCKED_STATUSES = {"ENV_BLOCKED", "CONTRACT_BLOCKED", "THREAD_BLOCKED", "PM_BLOCKED"}
POST_DEPENDENCY_STATUSES = {
    "READY_FOR_IMPL",
    "IN_IMPL",
    "READY_FOR_INTEGRATION",
    "IN_INTEGRATION",
    "READY_FOR_CLOSURE",
    "VERIFIED",
    "CLOSED",
}


@dataclass
class LoadedTask:
    path: Path
    task: dict[str, Any]
    evidence: dict[str, Any] | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PM dispatch task.yaml and evidence.yaml.")
    parser.add_argument("task", nargs="?", help="Path to one docs/tasks/<TASK>/task.yaml")
    parser.add_argument("--tasks-dir", help="Validate every */task.yaml in this docs/tasks directory")
    parser.add_argument("--evidence", help="Override evidence.yaml path for single-task validation")
    parser.add_argument("--schema-dir", help="Directory containing task.schema.json and evidence.schema.json")
    parser.add_argument("--now", help="Override current time, ISO-8601. Defaults to current UTC time")
    args = parser.parse_args()

    if not args.task and not args.tasks_dir:
        parser.error("provide a task.yaml path or --tasks-dir")

    script_dir = Path(__file__).resolve().parent
    schema_dir = Path(args.schema_dir).resolve() if args.schema_dir else script_dir.parent / "references" / "schemas"
    task_schema = load_structured_file(schema_dir / "task.schema.json")
    evidence_schema = load_structured_file(schema_dir / "evidence.schema.json")
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)

    errors: list[str] = []
    warnings: list[str] = []
    loaded: list[LoadedTask] = []

    task_paths = [Path(args.task)] if args.task else sorted(Path(args.tasks_dir).glob("*/task.yaml"))
    for task_path in task_paths:
        task_path = task_path.resolve()
        try:
            task = load_structured_file(task_path)
            errors.extend(validate_schema(task, task_schema, f"{task_path}", task_schema))
        except Exception as exc:
            errors.append(f"{task_path}: cannot load task: {exc}")
            continue

        evidence_path = evidence_file_for(task_path, task, args.evidence if len(task_paths) == 1 else None)
        evidence = None
        if evidence_path.exists():
            try:
                evidence = load_structured_file(evidence_path)
                errors.extend(validate_schema(evidence, evidence_schema, f"{evidence_path}", evidence_schema))
            except Exception as exc:
                errors.append(f"{evidence_path}: cannot load evidence: {exc}")
        elif task.get("status") in VERIFIED_STATUSES | BLOCKED_STATUSES | {"READY_FOR_CLOSURE"}:
            errors.append(f"{task_path}: status {task.get('status')} requires evidence file {evidence_path}")

        loaded.append(LoadedTask(task_path, task, evidence))

    for item in loaded:
        item_errors, item_warnings = validate_gate_policy(item, now)
        errors.extend(item_errors)
        warnings.extend(item_warnings)

    graph_errors, graph_warnings = validate_dependency_graph_and_locks(loaded, now)
    errors.extend(graph_errors)
    warnings.extend(graph_warnings)

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PM dispatch validation passed ({len(loaded)} task(s)).")
    return 0


def evidence_file_for(task_path: Path, task: dict[str, Any], override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    configured = task.get("verification", {}).get("evidence_file")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else (task_path.parent / path).resolve()
    return task_path.with_name("evidence.yaml")


def validate_gate_policy(item: LoadedTask, now: datetime) -> tuple[list[str], list[str]]:
    task = item.task
    evidence = item.evidence
    prefix = str(item.path)
    errors: list[str] = []
    warnings: list[str] = []

    open_blockers = [b for b in task.get("blockers", []) if b.get("status") == "open"]
    if task.get("status") in VERIFIED_STATUSES and open_blockers:
        errors.append(f"{prefix}: verified-like status is blocked by open blockers: {ids(open_blockers)}")

    for run in task.get("runs", []):
        if run.get("status") in ACTIVE_RUN_STATUSES:
            lease = latest_lease(run)
            if not lease:
                errors.append(f"{prefix}: active run {run.get('run_id')} has no lease")
                continue
            expires_at = parse_time(lease.get("expires_at"))
            if expires_at <= now:
                errors.append(f"{prefix}: active run {run.get('run_id')} lease expired at {lease.get('expires_at')}")
            if not lease.get("holder"):
                errors.append(f"{prefix}: active run {run.get('run_id')} lease is missing holder")

    active_by_gate: dict[str, list[str]] = {}
    for run in task.get("runs", []):
        if run.get("status") in ACTIVE_RUN_STATUSES and not run.get("allow_parallel", False):
            active_by_gate.setdefault(run.get("gate", "unknown"), []).append(run.get("run_id", "unknown"))
    for gate, run_ids in active_by_gate.items():
        if len(run_ids) > 1:
            errors.append(f"{prefix}: duplicate active non-parallel runs for gate {gate}: {', '.join(run_ids)}")

    dispatch = task.get("dispatch", {})
    strategy = dispatch.get("strategy")
    active_runs = [run for run in task.get("runs", []) if run.get("status") in ACTIVE_RUN_STATUSES]
    if strategy == "direct" and active_runs:
        errors.append(f"{prefix}: dispatch.strategy=direct cannot have active worker runs: {ids(active_runs, 'run_id')}")
    if strategy == "direct" and dispatch.get("worker_required"):
        errors.append(f"{prefix}: dispatch.strategy=direct requires worker_required=false")
    if strategy == "direct" and dispatch.get("heartbeat_required"):
        errors.append(f"{prefix}: dispatch.strategy=direct requires heartbeat_required=false")
    if strategy == "single-worker" and len(active_runs) > 1:
        errors.append(f"{prefix}: dispatch.strategy=single-worker allows at most one active run")
    if strategy in {"single-worker", "batch-worker", "full-dispatch"} and dispatch.get("worker_required") is False:
        errors.append(f"{prefix}: dispatch.strategy={strategy} requires worker_required=true")

    if not evidence:
        return errors, warnings

    if evidence.get("task_id") != task.get("id"):
        errors.append(f"{prefix}: evidence task_id {evidence.get('task_id')} does not match task id {task.get('id')}")

    conclusion = evidence.get("conclusion", {})
    if task.get("status") == "VERIFIED":
        if conclusion.get("status") != "VERIFIED":
            errors.append(f"{prefix}: task VERIFIED but evidence conclusion is {conclusion.get('status')}")
        if conclusion.get("mock_based"):
            errors.append(f"{prefix}: task VERIFIED cannot use mock_based evidence; use L*_VERIFIED_MOCK or PARTIAL_VERIFIED")

    if task.get("status", "").endswith("_VERIFIED_MOCK"):
        if not conclusion.get("mock_based") or not conclusion.get("accepted_fallback"):
            errors.append(f"{prefix}: mock verification requires mock_based=true and accepted_fallback")

    enforce_verification = task.get("status") in VERIFIED_STATUSES | {"READY_FOR_CLOSURE"}
    required_levels = task.get("verification", {}).get("required_levels", [])
    levels = evidence.get("verification", {}).get("levels", {})
    if enforce_verification:
        for level in required_levels:
            level_status = levels.get(level, {}).get("status")
            if level_status not in {"pass", "pass_mock"}:
                errors.append(f"{prefix}: required {level} evidence is {level_status or 'missing'}")
            if level_status == "pass_mock" and not conclusion.get("accepted_fallback"):
                errors.append(f"{prefix}: {level} uses mock evidence without accepted_fallback")

    artifacts = evidence.get("artifacts", {})
    surfaces = [s.lower() for s in evidence.get("verification", {}).get("changed_surface", [])]
    needs_l2 = "L2" in required_levels or any(matches_any(s, ["api", "dto", "status", "async", "service"]) for s in surfaces)
    needs_l3 = "L3" in required_levels or any(matches_any(s, ["ui", "page", "button", "tab", "modal", "route", "browser"]) for s in surfaces)
    needs_release = any(matches_any(s, ["sql", "schema", "migration", "startup", "package", "release", "static"]) for s in surfaces)

    if enforce_verification:
        if needs_l2 and not (artifacts.get("api") or artifacts.get("sql") or artifacts.get("commands")):
            errors.append(f"{prefix}: L2/API-like change requires api, sql, or command evidence")
        if needs_l3 and not artifacts.get("browser"):
            errors.append(f"{prefix}: L3/UI-like change requires browser evidence")
        if needs_release and not (artifacts.get("upgrade_path") or artifacts.get("release_path")):
            errors.append(f"{prefix}: SQL/release-like change requires upgrade_path or release_path evidence")
        if "L4" in required_levels and not (conclusion.get("real_chain_verified") or conclusion.get("accepted_fallback")):
            errors.append(f"{prefix}: L4 requires real_chain_verified=true or accepted_fallback")

    if conclusion.get("status") in VERIFIED_STATUSES and evidence.get("blockers"):
        unresolved = [b for b in evidence.get("blockers", []) if b.get("status") == "open"]
        if unresolved:
            errors.append(f"{prefix}: evidence conclusion is verified-like but has open blockers: {ids(unresolved)}")

    if task.get("status") in VERIFIED_STATUSES and task.get("closure", {}).get("status") == "open":
        warnings.append(f"{prefix}: verified task has closure.status=open; consider READY_FOR_CLOSURE or closed")

    return errors, warnings


def validate_dependency_graph_and_locks(items: list[LoadedTask], now: datetime) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    by_id = {item.task.get("id"): item for item in items}

    for item in items:
        task = item.task
        if task.get("status") in POST_DEPENDENCY_STATUSES:
            for dep in task.get("dependencies", {}).get("requires", []):
                dep_id = dep.get("task_id")
                required = dep.get("required_status")
                actual = by_id.get(dep_id).task.get("status") if dep_id in by_id else dep.get("status")
                if actual != required:
                    errors.append(f"{item.path}: dependency {dep_id} is {actual}, requires {required}")

    active_locks: dict[str, list[tuple[LoadedTask, dict[str, Any]]]] = {}
    for item in items:
        for lock in item.task.get("resources", {}).get("locks", []):
            if lock.get("status") not in ACTIVE_LOCK_STATUSES:
                continue
            expires = lock.get("lease_expires_at")
            if expires and parse_time(expires) <= now:
                errors.append(f"{item.path}: resource lock {lock.get('resource_id')} expired at {expires}")
                continue
            active_locks.setdefault(lock.get("resource_id", "unknown"), []).append((item, lock))

    for resource_id, locks in active_locks.items():
        exclusive = [pair for pair in locks if pair[1].get("mode") == "exclusive"]
        if exclusive and len(locks) > 1:
            holders = ", ".join(f"{item.task.get('id')}:{lock.get('holder_run_id')}" for item, lock in locks)
            errors.append(f"resource {resource_id}: exclusive lock conflict across active holders: {holders}")
        elif len(exclusive) > 1:
            holders = ", ".join(f"{item.task.get('id')}:{lock.get('holder_run_id')}" for item, lock in exclusive)
            errors.append(f"resource {resource_id}: duplicate exclusive locks: {holders}")

    return errors, warnings


def latest_lease(run: dict[str, Any]) -> dict[str, Any] | None:
    attempts = run.get("attempts") or []
    for attempt in reversed(attempts):
        lease = attempt.get("lease")
        if lease:
            return lease
    return None


def matches_any(value: str, needles: list[str]) -> bool:
    return any(needle in value for needle in needles)


def ids(items: list[dict[str, Any]], key: str = "id") -> str:
    return ", ".join(str(item.get(key, "unknown")) for item in items)


def load_structured_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return parse_yaml_subset(text)


def parse_yaml_subset(text: str) -> Any:
    raw_lines = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "\t" in line:
            raise ValueError(f"tabs are not supported in YAML fallback parser at line {lineno}")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("|") or stripped.endswith(">"):
            raise ValueError("block scalars require PyYAML; install PyYAML or use quoted strings")
        raw_lines.append((len(line) - len(line.lstrip(" ")), stripped, lineno))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(raw_lines):
            return {}, index
        if raw_lines[index][0] < indent:
            return {}, index
        is_list = raw_lines[index][1].startswith("- ")
        return parse_list(index, indent) if is_list else parse_dict(index, indent)

    def parse_dict(index: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while index < len(raw_lines):
            current_indent, stripped, lineno = raw_lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"unexpected indentation at line {lineno}")
            if stripped.startswith("- "):
                break
            key, value = split_key_value(stripped, lineno)
            index += 1
            if value == "":
                if index < len(raw_lines) and raw_lines[index][0] > current_indent:
                    child, index = parse_block(index, raw_lines[index][0])
                    result[key] = child
                else:
                    result[key] = None
            else:
                result[key] = parse_scalar(value)
        return result, index

    def parse_list(index: int, indent: int) -> tuple[list[Any], int]:
        result: list[Any] = []
        while index < len(raw_lines):
            current_indent, stripped, lineno = raw_lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"unexpected indentation at line {lineno}")
            if not stripped.startswith("- "):
                break
            item = stripped[2:].strip()
            index += 1
            if not item:
                if index < len(raw_lines) and raw_lines[index][0] > current_indent:
                    child, index = parse_block(index, raw_lines[index][0])
                    result.append(child)
                else:
                    result.append(None)
            elif ":" in item and not item.startswith(("'", '"')):
                key, value = split_key_value(item, lineno)
                obj: dict[str, Any] = {key: parse_scalar(value) if value else None}
                if index < len(raw_lines) and raw_lines[index][0] > current_indent:
                    child, index = parse_block(index, raw_lines[index][0])
                    if isinstance(child, dict):
                        obj.update(child)
                    else:
                        obj[key] = child
                result.append(obj)
            else:
                result.append(parse_scalar(item))
        return result, index

    parsed, final_index = parse_block(0, raw_lines[0][0] if raw_lines else 0)
    if final_index != len(raw_lines):
        raise ValueError("could not parse complete YAML document")
    return parsed


def split_key_value(text: str, lineno: int) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"expected key: value at line {lineno}")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"empty key at line {lineno}")
    return key, value.strip()


def parse_scalar(value: str) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(part.strip()) for part in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def validate_schema(value: Any, schema: dict[str, Any], path: str, root: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = resolve_ref(schema, root)
    expected = schema.get("type")
    if expected is not None and not type_matches(value, expected):
        errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
        return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']}, got {value!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required key {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}: additional property is not allowed")
        for key, child in value.items():
            if key in properties:
                errors.extend(validate_schema(child, resolve_ref(properties[key], root), f"{path}.{key}", root))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(validate_schema(item, resolve_ref(item_schema, root), f"{path}[{index}]", root))

    return errors


def resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported schema ref {ref}")
    target: Any = root
    for part in ref[2:].split("/"):
        target = target[part]
    return target


def type_matches(value: Any, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(type_matches(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def parse_time(value: Any) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text = text + "T00:00:00+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the compact, deterministic preflight before dispatching a Worker."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_context_packet import build_context_packet, select_run  # noqa: E402
from build_evidence_digest import build_evidence_digest  # noqa: E402
from build_project_snapshot import build_project_snapshot  # noqa: E402
from check_coordinator_budget import build_report, find_session  # noqa: E402
from select_codex_execution import missing_tools  # noqa: E402
from manage_recovery_ledger import (  # noqa: E402
    default_path,
    ensure_ledger,
    execution_error,
)
from validate_pm_dispatch import (  # noqa: E402
    assert_supported_schema,
    compose_task_runtime,
    load_structured_file,
    runtime_file_for,
    parse_time,
    validate_codex_heartbeat_automation,
    validate_schema,
)


def now_iso(value: str | None) -> str:
    return value or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def assert_heartbeat_dispatch_ready(
    task_path: Path,
    task: dict,
    automation_dir: Path | None,
    now: datetime | None = None,
) -> str | None:
    dispatch = task.get("dispatch") or {}
    if dispatch.get("strategy") == "direct" or not dispatch.get("worker_required"):
        return None
    effective = task
    if task.get("schema_version") == "4":
        runtime_path = runtime_file_for(task_path, task, None)
        if runtime_path is None or not runtime_path.exists():
            raise ValueError("Worker dispatch requires a Runtime sidecar")
        runtime = load_structured_file(runtime_path)
        effective = compose_task_runtime(task, runtime)
        dispatch = effective.get("dispatch") or {}
    resolution = dispatch.get("resolution") or {}
    if resolution.get("provider") == "codex-subagent":
        if (resolution.get("monitor_mode") != "milestone"
                or resolution.get("worker_type") != "codex-subagent"
                or "heartbeat" in dispatch.get("required_capabilities", [])
                or dispatch.get("heartbeat_required") or dispatch.get("heartbeat")):
            raise ValueError("native agents require milestone monitoring without Heartbeat")
        run = select_run(effective.get("runs", []))
        if not run:
            raise ValueError("native agent dispatch requires a Run")
        assert_provisioning_ready(run, now)
        return None
    if resolution.get("provider") != "codex":
        return None
    if resolution.get("worker_type") != "codex-thread":
        raise ValueError("Codex worker dispatch requires worker_type=codex-thread")
    if dispatch.get("heartbeat_required") is not True:
        raise ValueError(
            "Visible Codex worker dispatch requires heartbeat_required=true because "
            "create_thread has no verified parent callback"
        )
    if resolution.get("monitor_mode") != "heartbeat":
        raise ValueError("Codex worker dispatch requires monitor_mode=heartbeat")
    heartbeat = dispatch.get("heartbeat")
    if not isinstance(heartbeat, dict) or heartbeat.get("status") != "active":
        raise ValueError("Codex worker dispatch requires an active coordinator Heartbeat before create")
    for field in ("automation_id", "coordinator_thread_id", "target_run_id"):
        if not heartbeat.get(field):
            raise ValueError(f"Codex worker dispatch Heartbeat requires {field}")
    if int(str(resolution.get("adapter_version") or "0")) >= 13 and not isinstance(
        heartbeat.get("coordinator_epoch"), int
    ):
        raise ValueError("Codex v13+ Heartbeat requires coordinator_epoch")
    target_run = next(
        (
            run
            for run in effective.get("runs", [])
            if run.get("run_id") == heartbeat.get("target_run_id")
        ),
        None,
    )
    if not isinstance(target_run, dict):
        raise ValueError("Codex worker dispatch Heartbeat target Run is missing")
    assert_provisioning_ready(target_run, now)
    if automation_dir is not None:
        errors: list[str] = []
        validate_codex_heartbeat_automation(
            heartbeat,
            automation_dir.resolve(),
            errors,
            str(task_path),
        )
        if errors:
            raise ValueError("; ".join(errors))
    return str(heartbeat["automation_id"])


def assert_provisioning_ready(run: dict, now: datetime | None) -> None:
    if run.get("worker_id"):
        return
    provisioning = run.get("provisioning")
    if run.get("status") != "provisioning" or not isinstance(provisioning, dict):
        raise ValueError("Worker creation without worker_id requires a provisioning Run")
    if provisioning.get("status") != "pending":
        raise ValueError("Worker creation requires pending provisioning")
    if parse_time(provisioning.get("deadline_at")) <= (now or datetime.now(timezone.utc)):
        raise ValueError("Worker provisioning deadline expired; roll it back")


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
    automation_dir: Path | None = None,
    coordinator_session_dir: Path | None = None,
    mode: str | None = None,
    objective: str | None = None,
    purpose: str = "execute",
    recovery_attempt: str | None = None,
    host_tools: list[str] | dict | None = None,
) -> dict[str, str | None]:
    task_path = task_path.resolve()
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_iso(generated_at)
    evidence_path = task_path.parent / "evidence.yaml"
    task = load_structured_file(task_path)
    runtime_path = runtime_file_for(task_path, task, None)
    runtime = load_structured_file(runtime_path) if runtime_path and runtime_path.exists() else None
    effective = compose_task_runtime(task, runtime)
    if host_tools is not None and purpose == "execute":
        provider = (effective.get("dispatch", {}).get("resolution") or {}).get("provider")
        missing = missing_tools(provider, host_tools, effective.get("dispatch", {}).get("required_capabilities"))
        if missing:
            raise ValueError(f"unavailable host tools for {provider}: {missing}")
    run = select_run(effective.get("runs", []))
    effective_mode = mode or ("continuation" if run and run.get("worker_id") else "initial")
    schema_dir = SCRIPT_DIR.parent / "references" / "schemas"
    ledger_path = default_path(task_path)
    if purpose == "execute" and effective_mode == "continuation" and run and run.get("worker_id") and not ledger_path.is_file():
        raise ValueError("continuation is missing its canonical Recovery Ledger; reconcile/import legacy history first")
    legacy_path = output_dir / "recovery-ledger.json"
    if purpose == "execute" and legacy_path != ledger_path and legacy_path.is_file() and not ledger_path.exists():
        if load_structured_file(legacy_path).get("gates"):
            raise ValueError("legacy recovery history exists in the output directory; import it before preflight")
    if purpose == "execute":
        ensure_ledger(task_path, task["id"], stamp, schema_dir)
    ledger = load_structured_file(ledger_path) if ledger_path.is_file() else None
    if purpose == "execute":
        error = execution_error(ledger, gate or (run or {}).get("gate") or task.get("lifecycle", {}).get("phase"), recovery_attempt)
        if error:
            raise ValueError(error)
    heartbeat_id = assert_heartbeat_dispatch_ready(
        task_path, task, automation_dir, parse_time(stamp)
    ) if purpose == "execute" else None
    coordinator_report = None
    if heartbeat_id:
        runtime_path = runtime_file_for(task_path, task, None)
        runtime = load_structured_file(runtime_path) if runtime_path else {}
        heartbeat = runtime.get("heartbeat") or {}
        coordinator_thread_id = str(heartbeat.get("coordinator_thread_id") or "")
        session_path = (
            find_session(coordinator_session_dir, coordinator_thread_id)
            if coordinator_session_dir is not None
            else None
        )
        coordinator_report = build_report(
            session_path,
            thread_id=coordinator_thread_id,
            epoch=int(heartbeat.get("coordinator_epoch") or 1),
            measured_at=stamp,
        )
        coordinator_schema = load_structured_file(
            SCRIPT_DIR.parent
            / "references"
            / "schemas"
            / "coordinator-budget.schema.json"
        )
        coordinator_errors = validate_schema(
            coordinator_report,
            coordinator_schema,
            "coordinator-budget.json",
            coordinator_schema,
        )
        if coordinator_errors:
            raise ValueError("invalid Coordinator Budget:\n" + "\n".join(coordinator_errors))
        write_json(output_dir / "coordinator-budget.json", coordinator_report)
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

    packet_path = output_dir / "active-context.json"
    packet, packet_text = build_context_packet(
        task_path,
        packet_path,
        mode=effective_mode,
        objective=objective,
        purpose=purpose,
        recovery_attempt=recovery_attempt,
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
        "mode": effective_mode,
        "recovery_ledger": str(ledger_path) if ledger_path.is_file() else None,
        "evidence_digest": digest_result,
        "project_snapshot": snapshot["snapshot_sha256"],
        "context_packet": packet["packet_sha256"],
        "heartbeat": heartbeat_id,
        "coordinator_budget": (
            coordinator_report["action"] if coordinator_report else None
        ),
        "output_dir": str(output_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the compact PM dispatch preflight bundle.")
    parser.add_argument("task")
    parser.add_argument("--project-root")
    parser.add_argument("--output-dir")
    parser.add_argument("--mode", choices=["initial", "continuation"], help="Defaults to continuation when reusing a Worker")
    parser.add_argument("--objective", help="Remaining work only for a continuation")
    parser.add_argument("--purpose", choices=["execute", "inspect"], default="execute")
    parser.add_argument("--recovery-attempt", help="Pending recovery attempt_key reserved before retrying")
    parser.add_argument("--gate", choices=["contract", "implementation", "integration", "verification", "closure"])
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--verification-command", action="append", default=[])
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument("--now")
    parser.add_argument("--host-tools", help="JSON array of live tool names")
    parser.add_argument(
        "--automation-dir",
        help="Codex automations directory; defaults to $CODEX_HOME/automations",
    )
    parser.add_argument(
        "--coordinator-session-dir",
        help="Codex session directory; defaults to $CODEX_HOME/sessions",
    )
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
    automation_dir = (
        Path(args.automation_dir).resolve()
        if args.automation_dir
        else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
        / "automations"
    )
    coordinator_session_dir = (
        Path(args.coordinator_session_dir).resolve()
        if args.coordinator_session_dir
        else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
        / "sessions"
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
        automation_dir=automation_dir,
        coordinator_session_dir=coordinator_session_dir,
        mode=args.mode,
        objective=args.objective,
        purpose=args.purpose,
        recovery_attempt=args.recovery_attempt,
        host_tools=json.loads(Path(args.host_tools).read_text()) if args.host_tools else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

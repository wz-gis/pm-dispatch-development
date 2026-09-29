from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_pm_dispatch.py"
NOW = "2026-07-13T12:00:00Z"


def autonomy_policy() -> dict:
    return {
        "default_action": "proceed",
        "clarification_policy": "material-irreversible-only",
        "blocker_policy": "hard-only",
        "verification_policy": "risk-scaled",
        "recovery": {
            "same_method_retries": 1,
            "alternate_method_attempts": 2,
            "rediscovery_limit": 1,
        },
    }


def base_task(task_id: str = "BUG-041") -> dict:
    return {
        "schema_version": "3",
        "id": task_id,
        "display_name": f"{task_id} P1 AA 最近诊断记录",
        "title": "最近诊断记录",
        "type": "bug",
        "priority": "P1",
        "status": "TRIAGED",
        "mode": "single-project",
        "area": ["AA"],
        "lifecycle": {"phase": "triage", "owner": "pm", "next_action": "define acceptance"},
        "verification": {
            "required_levels": ["L1"],
            "gate_policy": "default",
            "evidence_file": "evidence.json",
            "status": "PENDING",
            "mock_allowed": False,
            "missing": [],
        },
        "quality_checks": {
            "policy": "risk-scaled",
            "checks": [
                {
                    "id": "unit-test",
                    "requirement": "required",
                    "when_changed_surface": [],
                    "evidence_kinds": ["command"],
                }
            ],
        },
        "blockers": [],
        "closure": {"status": "open"},
        "dependencies": {"requires": [], "blocks": [], "graph_checked_at": NOW},
        "resources": {"locks": []},
        "dispatch": {
            "strategy": "direct",
            "provider_policy": {"mode": "local", "provider": "local"},
            "required_capabilities": [],
            "required_evidence_kinds": [],
            "reason": "small task",
            "worker_required": False,
            "heartbeat_required": False,
            "selected_at": NOW,
            "max_parallel_workers": None,
            "reasoning_profile": None,
            "fallback_policy": None,
            "resolution": None,
            "autonomy_policy": autonomy_policy(),
            "design_freeze": None,
            "worker_reuse": None,
            "batch": None,
            "heartbeat": None,
            "escalation_triggers": [],
        },
        "runs": [],
        "last_updated": NOW,
    }


def artifact(kind: str, artifact_id: str | None = None) -> dict:
    return {
        "artifact_id": artifact_id or f"{kind}-001",
        "kind": kind,
        "source": "automated-test",
        "subject": f"{kind} verification",
        "result": "pass",
        "captured_at": NOW,
        "evidence_ref": f"evidence/{kind}-001.json",
    }


def frozen_design() -> dict:
    freeze = {
        "status": "frozen",
        "frozen_at": NOW,
        "scope": ["frontend/app"],
        "constraints": ["Keep existing routes compatible."],
        "acceptance": ["L1 command evidence passes."],
        "fingerprint": None,
        "change_policy": "material-only-new-attempt",
    }
    payload = {
        key: freeze[key]
        for key in ("scope", "constraints", "acceptance", "change_policy")
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    freeze["fingerprint"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return freeze


def base_evidence(task_id: str = "BUG-041") -> dict:
    return {
        "schema_version": "2",
        "task_id": task_id,
        "generated_at": NOW,
        "verification": {
            "changed_surface": ["backend"],
            "original_user_path": "open existing record",
            "runtime_shape": "dev",
            "test_data": ["existing-record"],
            "levels": {
                "L1": {
                    "status": "pass",
                    "summary": "tests passed",
                    "evidence_refs": ["command-001"],
                    "commands": ["python3 -m unittest"],
                }
            },
            "existing_data_regression": "passed",
            "uncovered_items": [],
        },
        "quality_checks": [
            {
                "id": "unit-test",
                "status": "passed",
                "tool": "python-unittest",
                "summary": "Unit tests passed.",
                "evidence_refs": ["command-001"],
                "skip_reason": None,
                "checked_at": NOW,
            }
        ],
        "artifacts": {
            "commands": [
                {
                    **artifact("command", "command-001"),
                    "command": "python3 -m unittest",
                    "exit_code": 0,
                }
            ],
            "commits": [],
            "files_changed": [],
            "api": [],
            "sql": [],
            "browser": [],
            "screenshots": [],
            "logs": [],
            "ids": [],
            "upgrade_path": [],
            "release_path": [],
        },
        "runs": [],
        "blockers": [],
        "conclusion": {
            "status": "VERIFIED",
            "evidence_level": "L1",
            "mock_based": False,
            "real_chain_verified": True,
            "accepted_fallback": None,
        },
    }


def verified_task(task_id: str = "BUG-041") -> dict:
    task = base_task(task_id)
    task["status"] = "VERIFIED"
    task["lifecycle"]["phase"] = "closure"
    task["closure"]["status"] = "ready"
    task["verification"]["status"] = "L1_VERIFIED"
    return task


def codex_run(task_id: str = "SPEC-101", index: int = 1) -> dict:
    worker_name = f"{task_id}-impl-w{index:02d}"
    run_id = f"run-{worker_name}"
    attempt_id = f"attempt-{worker_name}-a01"
    return {
        "run_id": run_id,
        "gate": "implementation",
        "worker_type": "codex-thread",
        "worker_name": worker_name,
        "worker_label": f"{task_id} P1 AA 新增页面 [impl w{index:02d}]",
        "worker_id": f"codex-thread:thread-{index}",
        "worker_replacement_reason": None,
        "provider": "codex",
        "adapter_version": "15",
        "model_id": None,
        "reasoning_profile": "standard",
        "provider_reasoning_effort": "inherit",
        "resolution_reason": "normal task",
        "design_fingerprint": frozen_design()["fingerprint"],
        "status": "running",
        "allow_parallel": index > 1,
        "started_at": NOW,
        "finished_at": None,
        "wait_budget": {
            "policy": "single-short",
            "max_calls": 1,
            "max_timeout_ms": 30000,
            "enforced_at": NOW,
        },
        "inspection_budget": {
            "policy": "incremental-debounce",
            "min_interval_seconds": 600,
            "max_calls_per_cycle": 1,
            "enforced_at": NOW,
        },
        "attempts": [
            {
                "attempt_id": attempt_id,
                "status": "running",
                "started_at": NOW,
                "finished_at": None,
                "lease": {
                    "holder": run_id,
                    "acquired_at": NOW,
                    "heartbeat_at": NOW,
                    "expires_at": "2026-07-13T13:00:00Z",
                    "renew_count": 0,
                    "progress_seq": 0,
                    "last_progress_at": NOW,
                    "last_progress_summary": "worker dispatched",
                    "event_cursor": None,
                    "liveness_state": "live",
                    "monitor_gap_started_at": None,
                    "disconnect_probe_count": 0,
                    "disconnect_first_seen_at": None,
                },
            }
        ],
    }


def codex_dispatch() -> dict:
    return {
        "strategy": "single-worker",
        "provider_policy": {"mode": "pinned", "provider": "codex"},
        "required_capabilities": ["background-worker", "code-edit", "git", "heartbeat", "shell"],
        "required_evidence_kinds": ["command", "log"],
        "reason": "implementation requires an isolated worker",
        "worker_required": True,
        "heartbeat_required": True,
        "selected_at": NOW,
        "max_parallel_workers": 1,
        "reasoning_profile": "standard",
        "fallback_policy": {
            "mode": "strict",
            "allowed_providers": ["codex"],
            "allow_manual_monitoring": False,
        },
        "resolution": {
            "provider": "codex",
            "adapter_version": "15",
            "model_id": None,
            "reasoning_profile": "standard",
            "provider_reasoning_effort": "inherit",
            "worker_type": "codex-thread",
            "monitor_mode": "heartbeat",
            "capabilities": ["background-worker", "code-edit", "git", "heartbeat", "shell"],
            "evidence_kinds": ["command", "log"],
            "resolved_at": NOW,
            "reason": "pinned provider satisfies the requested capabilities",
        },
        "autonomy_policy": autonomy_policy(),
        "design_freeze": frozen_design(),
        "worker_reuse": {
            "mode": "sticky",
            "reuse_across_gates": True,
            "max_runs_per_worker": 6,
            "replacement_triggers": [
                "irrecoverable-worker",
                "safety-boundary-change",
                "design-freeze-change",
                "provider-change",
                "context-saturated",
                "independent-review",
            ],
        },
        "batch": None,
        "heartbeat": {
            "automation_id": "automation-001",
            "coordinator_thread_id": "codex-thread:pm-1",
            "coordinator_epoch": 1,
            "target_run_id": "run-SPEC-101-impl-w01",
            "context_policy": "coordinator",
            "scan_scope": "incremental",
            "read_set": ["worker-status", "lease", "latest-milestone"],
            "full_scan_triggers": [
                "milestone",
                "terminal",
                "safety-boundary-change",
                "design-freeze-change",
            ],
            "prompt_max_chars": 220,
            "interval_minutes": 10,
            "max_checks": 6,
            "stop_condition": "run terminal",
            "lightweight": True,
            "status": "active",
        },
        "escalation_triggers": [],
    }


def thin_wrapper_delegation() -> dict:
    return {
        "mode": "thin-wrapper-subagent",
        "agent": "external-agent-test",
        "initial_invocation_limit": 1,
        "repair_invocation_limit": 1,
        "retry_policy": "focused-verification-failure-only",
    }


def split_runtime(task: dict) -> tuple[dict, dict]:
    task = copy.deepcopy(task)
    dispatch = task["dispatch"]
    runtime = {
        "schema_version": "1",
        "task_id": task["id"],
        "task_schema_version": "4",
        "resolution": dispatch.pop("resolution"),
        "selected_at": dispatch.pop("selected_at"),
        "heartbeat": dispatch.pop("heartbeat"),
        "resources": task.pop("resources"),
        "runs": task.pop("runs"),
        "event_log_file": "events.jsonl",
        "last_updated": task["last_updated"],
    }
    for run in runtime["runs"]:
        run.setdefault("continuation_token", None)
        run.setdefault("event_cursor", None)
        run.setdefault("last_operation", None)
        run.setdefault("last_idempotency_key", None)
    task["schema_version"] = "4"
    task["runtime_file"] = "runtime.yaml"
    return task, runtime


def wait_event(
    event_id: str,
    event_type: str,
    occurred_at: str,
    *,
    source: str = "coordinator",
) -> dict:
    payload = {
        "operation": "inspect",
        "source": source,
        "timeout_ms": 0,
    }
    if event_type == "terminal-wait-authorized":
        payload = {"source": source, "timeout_ms": 30000, "event_cursor": None}
    elif event_type == "terminal-wait-finished":
        payload = {
            "authorization_event_id": "wait-auth-001",
            "outcome": "timeout",
        }
    elif event_type == "status-inspect-authorized":
        payload = {
            "source": source,
            "reason": "scheduled",
            "cycle_id": event_id,
            "timeout_ms": 0,
            "event_cursor": None,
        }
    return {
        "schema_version": "1",
        "event_id": event_id,
        "event_type": event_type,
        "task_id": "SPEC-101",
        "occurred_at": occurred_at,
        "run_id": "run-SPEC-101-impl-w01",
        "attempt_id": "attempt-SPEC-101-impl-w01-a01",
        "provider": "codex",
        "worker_id": "codex-thread:thread-1",
        "payload": payload,
    }


def native_wait_record(call_id: str, timestamp: str, timeout_ms: int = 30000) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "item": {
                "type": "McpToolCall",
                "id": call_id,
                "server": "codex_app",
                "tool": "wait_threads",
                "arguments": {
                    "targets": [{"threadId": "thread-1"}],
                    "timeoutMs": timeout_ms,
                },
            },
        },
    }


class ValidatorCase(unittest.TestCase):
    def run_task(
        self,
        task: dict,
        evidence: dict | None = None,
        runtime: dict | None = None,
        runtime_events: list[dict] | None = None,
        adapters: list[dict] | None = None,
        automation_status: str | None = None,
        automation_interval: int | None = None,
        automation_prompt: str = "增量检查目标 Run 的 Worker 状态、Lease 和最新里程碑；终态立即收口，监控不可用则保持所有权。",
        automation_target_thread_id: str | None = None,
        codex_session_records: list[dict] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / task["id"]
            task_dir.mkdir()
            task_path = task_dir / "task.json"
            task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
            if runtime is not None:
                runtime_name = task.get("runtime_file") or "runtime.yaml"
                (task_dir / runtime_name).write_text(
                    json.dumps(runtime, ensure_ascii=False), encoding="utf-8"
                )
                event_name = runtime.get("event_log_file", "events.jsonl")
                event_text = "".join(
                    json.dumps(event, ensure_ascii=False) + "\n"
                    for event in (runtime_events or [])
                )
                (task_dir / event_name).write_text(event_text, encoding="utf-8")
            if evidence is not None:
                (task_dir / "evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
                )
            command = ["python3", str(VALIDATOR), str(task_path), "--now", NOW]
            if adapters is not None:
                adapter_dir = Path(tmp) / "adapters"
                adapter_dir.mkdir()
                for adapter in adapters:
                    path = adapter_dir / f"{adapter['provider']}.adapter.json"
                    path.write_text(json.dumps(adapter, ensure_ascii=False), encoding="utf-8")
                command.extend(["--adapter-dir", str(adapter_dir)])
            if automation_status is not None:
                automation_id = task["dispatch"]["heartbeat"]["automation_id"]
                automation_dir = Path(tmp) / "automations"
                automation_path = automation_dir / automation_id / "automation.toml"
                automation_path.parent.mkdir(parents=True)
                interval = automation_interval or task["dispatch"]["heartbeat"][
                    "interval_minutes"
                ]
                target_thread_id = (
                    automation_target_thread_id
                    or task["dispatch"]["heartbeat"]["coordinator_thread_id"]
                )
                automation_path.write_text(
                    "\n".join(
                        [
                            'kind = "heartbeat"',
                            f'prompt = {json.dumps(automation_prompt, ensure_ascii=False)}',
                            f'status = "{automation_status}"',
                            f'rrule = "FREQ=MINUTELY;INTERVAL={interval}"',
                            f'target_thread_id = "{target_thread_id}"',
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                command.extend(["--automation-dir", str(automation_dir)])
            if codex_session_records is not None:
                session_dir = Path(tmp) / "sessions"
                session_dir.mkdir()
                heartbeat = (
                    runtime.get("heartbeat")
                    if runtime is not None
                    else task.get("dispatch", {}).get("heartbeat")
                ) or {}
                coordinator_id = heartbeat.get("coordinator_thread_id", "coordinator")
                session_path = session_dir / f"rollout-{coordinator_id}.jsonl"
                session_path.write_text(
                    "".join(
                        json.dumps(record, ensure_ascii=False) + "\n"
                        for record in codex_session_records
                    ),
                    encoding="utf-8",
                )
                command.extend(["--codex-session-dir", str(session_dir)])
            return subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
            )

    def assert_invalid(self, task: dict, message: str, evidence: dict | None = None) -> None:
        result = self.run_task(task, evidence)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)

    def test_valid_display_name_and_direct_task_pass(self) -> None:
        result = self.run_task(base_task())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_task_v4_uses_runtime_sidecar(self) -> None:
        task = base_task()
        runtime = {
            "schema_version": "1",
            "task_id": task["id"],
            "task_schema_version": "4",
            "resolution": task["dispatch"].pop("resolution"),
            "selected_at": task["dispatch"].pop("selected_at"),
            "heartbeat": task["dispatch"].pop("heartbeat"),
            "resources": task.pop("resources"),
            "runs": task.pop("runs"),
            "event_log_file": "events.jsonl",
            "last_updated": NOW,
        }
        task["schema_version"] = "4"
        task["runtime_file"] = "runtime.yaml"
        result = self.run_task(task, runtime=runtime)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_task_v4_rejects_embedded_runtime_state(self) -> None:
        task = base_task()
        task["schema_version"] = "4"
        task["runtime_file"] = "runtime.yaml"
        result = self.run_task(task)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("keeps runs in Runtime", result.stderr)

    def test_display_name_must_match_id_priority_area_and_title(self) -> None:
        task = base_task()
        task["display_name"] = "BUG-041 P1 AA 错误标题"
        self.assert_invalid(task, "display_name must equal")

    def test_nonterminal_task_requires_open_closure(self) -> None:
        task = base_task()
        task["closure"]["status"] = "closed"
        self.assert_invalid(task, "requires closure.status=open")

    def test_id_prefix_must_match_type(self) -> None:
        task = base_task()
        task["type"] = "spec"
        self.assert_invalid(task, "does not match task type")

    def test_closed_requires_evidence_and_closed_state_matrix(self) -> None:
        task = base_task()
        task["status"] = "CLOSED"
        self.assert_invalid(task, "status CLOSED requires evidence")

    def test_partial_verified_requires_evidence(self) -> None:
        task = base_task()
        task["status"] = "PARTIAL_VERIFIED"
        self.assert_invalid(task, "status PARTIAL_VERIFIED requires evidence")

    def test_valid_closed_task_passes(self) -> None:
        task = base_task()
        task["status"] = "CLOSED"
        task["lifecycle"].update({"phase": "archive", "next_action": "none"})
        task["verification"]["status"] = "L1_VERIFIED"
        task["closure"] = {
            "status": "closed",
            "accepted_by": "pm",
            "accepted_at": NOW,
            "closed_at": NOW,
            "archived_to": "docs/archive/BUG-041",
        }
        result = self.run_task(task, base_evidence())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_required_quality_check_must_exist_at_closure(self) -> None:
        evidence = base_evidence()
        evidence["quality_checks"] = []
        self.assert_invalid(
            verified_task(), "required quality check 'unit-test' is missing", evidence
        )

    def test_passed_quality_check_requires_passing_artifact(self) -> None:
        evidence = base_evidence()
        evidence["artifacts"]["commands"][0].update(
            {"result": "fail", "exit_code": 1}
        )
        self.assert_invalid(
            verified_task(), "references non-passing artifact 'command-001'", evidence
        )

    def test_passed_quality_check_requires_declared_artifact_kind(self) -> None:
        task = verified_task()
        task["quality_checks"]["checks"][0]["evidence_kinds"] = ["log"]
        self.assert_invalid(
            task, "uses kind='command', expected one of ['log']", base_evidence()
        )

    def test_nonterminal_failed_quality_check_remains_recoverable(self) -> None:
        evidence = base_evidence()
        evidence["quality_checks"][0].update(
            {
                "status": "failed",
                "summary": "Focused test failed; repair remains in the same Attempt.",
                "evidence_refs": ["command-001"],
            }
        )
        evidence["artifacts"]["commands"][0].update(
            {"result": "fail", "exit_code": 1}
        )
        result = self.run_task(base_task(), evidence)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_untriggered_conditional_quality_check_may_be_skipped(self) -> None:
        task = verified_task()
        task["quality_checks"]["checks"].append(
            {
                "id": "security",
                "requirement": "conditional",
                "when_changed_surface": ["auth", "dependency", "secret"],
                "evidence_kinds": ["command", "log"],
            }
        )
        evidence = base_evidence()
        evidence["quality_checks"].append(
            {
                "id": "security",
                "status": "skipped",
                "tool": None,
                "summary": "No security-sensitive surface changed.",
                "evidence_refs": [],
                "skip_reason": "No configured trigger matched.",
                "checked_at": NOW,
            }
        )
        result = self.run_task(task, evidence)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_triggered_conditional_quality_check_cannot_be_skipped(self) -> None:
        task = verified_task()
        task["quality_checks"]["checks"].append(
            {
                "id": "security",
                "requirement": "conditional",
                "when_changed_surface": ["auth", "dependency", "secret"],
                "evidence_kinds": ["command", "log"],
            }
        )
        evidence = base_evidence()
        evidence["verification"]["changed_surface"] = ["auth service"]
        evidence["quality_checks"].append(
            {
                "id": "security",
                "status": "skipped",
                "tool": None,
                "summary": "Skipped security scan.",
                "evidence_refs": [],
                "skip_reason": "Not run.",
                "checked_at": NOW,
            }
        )
        self.assert_invalid(
            task, "required quality check 'security' cannot be skipped", evidence
        )

    def test_failed_optional_quality_check_blocks_closure(self) -> None:
        task = verified_task()
        task["quality_checks"]["checks"].append(
            {
                "id": "review",
                "requirement": "optional",
                "when_changed_surface": [],
                "evidence_kinds": ["log"],
            }
        )
        evidence = base_evidence()
        evidence["quality_checks"].append(
            {
                "id": "review",
                "status": "failed",
                "tool": "codex-review",
                "summary": "Review found an unresolved issue.",
                "evidence_refs": [],
                "skip_reason": None,
                "checked_at": NOW,
            }
        )
        self.assert_invalid(task, "quality check 'review' is failed and blocks closure", evidence)

    def test_evidence_quality_check_must_be_declared_by_task(self) -> None:
        evidence = base_evidence()
        evidence["quality_checks"].append(
            {
                "id": "undeclared-check",
                "status": "pending",
                "tool": None,
                "summary": "Unexpected result.",
                "evidence_refs": [],
                "skip_reason": None,
                "checked_at": None,
            }
        )
        self.assert_invalid(
            verified_task(), "is not declared by Task", evidence
        )

    def test_verified_rejects_unstructured_browser_evidence(self) -> None:
        task = base_task("SPEC-042")
        task.update({"display_name": "SPEC-042 P1 WEB 新增页面", "title": "新增页面", "type": "spec", "area": ["WEB"]})
        task["status"] = "VERIFIED"
        task["lifecycle"]["phase"] = "closure"
        task["closure"]["status"] = "ready"
        task["verification"].update({"required_levels": ["L3"], "status": "L3_VERIFIED"})
        evidence = base_evidence("SPEC-042")
        evidence["verification"]["changed_surface"] = ["ui page"]
        evidence["verification"]["levels"] = {"L3": {"status": "pass", "summary": "claimed"}}
        evidence["artifacts"]["browser"] = ["trust me"]
        self.assert_invalid(task, "expected object", evidence)

    def test_invalid_evidence_timestamp_is_rejected(self) -> None:
        task = base_task()
        task["status"] = "VERIFIED"
        task["lifecycle"]["phase"] = "closure"
        task["closure"]["status"] = "ready"
        task["verification"]["status"] = "L1_VERIFIED"
        evidence = base_evidence()
        evidence["generated_at"] = "not-a-date"
        self.assert_invalid(task, "invalid date-time", evidence)

    def test_invalid_active_lease_timestamp_is_reported_without_traceback(self) -> None:
        task = self.worker_task()
        task["runs"][0]["attempts"][0]["lease"]["expires_at"] = "not-a-date"
        result = self.run_task(task)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid date-time", result.stderr)
        self.assertNotIn("Traceback (most recent call last)", result.stderr)

    def test_level_evidence_ref_must_resolve_to_artifact(self) -> None:
        task = base_task()
        task["status"] = "VERIFIED"
        task["lifecycle"]["phase"] = "closure"
        task["closure"]["status"] = "ready"
        task["verification"]["status"] = "L1_VERIFIED"
        evidence = base_evidence()
        evidence["verification"]["levels"]["L1"]["evidence_refs"] = ["missing-artifact"]
        self.assert_invalid(task, "does not match an artifact_id", evidence)

    def test_in_impl_worker_strategy_requires_run(self) -> None:
        task = base_task("SPEC-101")
        task.update({"display_name": "SPEC-101 P1 AA 新增页面", "title": "新增页面", "type": "spec"})
        task["status"] = "IN_IMPL"
        task["lifecycle"]["phase"] = "implementation"
        task["dispatch"] = codex_dispatch()
        self.assert_invalid(task, "requires at least one run")

    def test_active_codex_run_requires_worker_id(self) -> None:
        task = self.worker_task()
        task["runs"][0]["worker_id"] = None
        self.assert_invalid(task, "active run requires worker_id")

    def test_provisioning_run_allows_bounded_workerless_state(self) -> None:
        task = self.worker_task()
        run = task["runs"][0]
        run["status"] = "provisioning"
        run["worker_id"] = None
        run["attempts"][0]["status"] = "provisioning"
        run["attempts"][0]["lease"] = None
        run["provisioning"] = {
            "transaction_id": "create-SPEC-101-a01",
            "status": "pending",
            "started_at": NOW,
            "deadline_at": "2026-07-13T12:02:00Z",
            "finished_at": None,
            "failure": None,
        }
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_expired_provisioning_requires_rollback(self) -> None:
        task = self.worker_task()
        run = task["runs"][0]
        run["status"] = "provisioning"
        run["worker_id"] = None
        run["attempts"][0]["status"] = "provisioning"
        run["attempts"][0]["lease"] = None
        run["provisioning"] = {
            "transaction_id": "create-SPEC-101-a01",
            "status": "pending",
            "started_at": "2026-07-13T11:55:00Z",
            "deadline_at": "2026-07-13T11:57:00Z",
            "finished_at": None,
            "failure": None,
        }
        self.assert_invalid(task, "roll it back")

    def test_duplicate_attempt_id_is_rejected(self) -> None:
        task = self.worker_task()
        task["runs"][0]["attempts"].append(copy.deepcopy(task["runs"][0]["attempts"][0]))
        self.assert_invalid(task, "duplicate attempt_id")

    def test_max_parallel_workers_is_enforced(self) -> None:
        task = self.worker_task()
        task["dispatch"]["strategy"] = "full-dispatch"
        task["runs"].append(codex_run(index=2))
        self.assert_invalid(task, "max_parallel_workers=1")

    def test_single_worker_requires_sticky_cross_gate_reuse(self) -> None:
        task = self.worker_task()
        task["dispatch"]["worker_reuse"]["reuse_across_gates"] = False
        self.assert_invalid(task, "requires sticky reuse across gates")

    def test_thin_wrapper_subagent_contract_passes(self) -> None:
        task = self.worker_task()
        task["dispatch"]["delegation"] = thin_wrapper_delegation()
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_thin_wrapper_requires_single_visible_codex_worker(self) -> None:
        task = self.worker_task()
        task["dispatch"]["delegation"] = thin_wrapper_delegation()
        task["dispatch"]["strategy"] = "full-dispatch"
        self.assert_invalid(task, "delegated subagent execution requires dispatch.strategy=single-worker")

    def test_thin_wrapper_requires_one_parallel_worker(self) -> None:
        task = self.worker_task()
        task["dispatch"]["delegation"] = thin_wrapper_delegation()
        task["dispatch"]["max_parallel_workers"] = 2
        self.assert_invalid(task, "delegated subagent execution requires max_parallel_workers=1")

    def test_thin_wrapper_requires_shell_capability(self) -> None:
        task = self.worker_task()
        task["dispatch"]["delegation"] = thin_wrapper_delegation()
        task["dispatch"]["required_capabilities"].remove("shell")
        self.assert_invalid(task, "delegated subagent wrapper lacks required capabilities: shell")

    def test_direct_strategy_rejects_subagent_delegation(self) -> None:
        task = base_task()
        task["dispatch"]["delegation"] = thin_wrapper_delegation()
        self.assert_invalid(task, "dispatch.strategy=direct requires delegation=null or omitted")

    def test_single_worker_reuses_same_worker_across_runs(self) -> None:
        task = self.worker_task()
        first = task["runs"][0]
        first["status"] = "succeeded"
        first["finished_at"] = NOW
        first["attempts"][0]["status"] = "succeeded"
        first["attempts"][0]["finished_at"] = NOW
        second = codex_run(index=2)
        second["worker_id"] = first["worker_id"]
        second["allow_parallel"] = False
        task["runs"].append(second)
        task["dispatch"]["heartbeat"]["target_run_id"] = second["run_id"]
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_single_worker_change_requires_structured_reason(self) -> None:
        task = self.worker_task()
        first = task["runs"][0]
        first["status"] = "succeeded"
        first["finished_at"] = NOW
        first["attempts"][0]["status"] = "succeeded"
        first["attempts"][0]["finished_at"] = NOW
        second = codex_run(index=2)
        second["allow_parallel"] = False
        task["runs"].append(second)
        task["dispatch"]["heartbeat"]["target_run_id"] = second["run_id"]
        self.assert_invalid(task, "without an allowed worker_replacement_reason")

    def test_single_worker_can_continue_past_legacy_run_limit(self) -> None:
        for legacy_limit in (None, 3, 8):
            with self.subTest(legacy_limit=legacy_limit):
                task = self.worker_task()
                reuse = task["dispatch"]["worker_reuse"]
                if legacy_limit is None:
                    reuse.pop("max_runs_per_worker", None)
                else:
                    reuse["max_runs_per_worker"] = legacy_limit
                worker_id = task["runs"][0]["worker_id"]
                task["runs"] = []
                for index in range(1, 10):
                    run = codex_run(index=index)
                    run["worker_id"] = worker_id
                    run["allow_parallel"] = False
                    if index < 9:
                        run["status"] = "succeeded"
                        run["finished_at"] = NOW
                        run["attempts"][0]["status"] = "succeeded"
                        run["attempts"][0]["finished_at"] = NOW
                    task["runs"].append(run)
                task["dispatch"]["heartbeat"]["target_run_id"] = task["runs"][-1]["run_id"]
                result = self.run_task(task)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_single_worker_allows_irrecoverable_worker_replacement(self) -> None:
        task = self.worker_task()
        first = task["runs"][0]
        first["status"] = "expired"
        first["finished_at"] = NOW
        first["attempts"][0]["status"] = "expired"
        first["attempts"][0]["finished_at"] = NOW
        second = codex_run(index=2)
        second["allow_parallel"] = False
        second["worker_replacement_reason"] = "irrecoverable-worker"
        task["runs"].append(second)
        task["dispatch"]["heartbeat"]["target_run_id"] = second["run_id"]
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_heartbeat_required_needs_automation_metadata(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat"] = None
        self.assert_invalid(task, "heartbeat metadata")

    def test_incremental_heartbeat_rejects_full_scan(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat"]["scan_scope"] = "full"
        self.assert_invalid(task, "expected one of ['incremental'], got 'full'")

    def test_incremental_heartbeat_has_fixed_read_set(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat"]["read_set"].append("task")
        self.assert_invalid(task, "expected at most 3 items")

    def test_unknown_liveness_holds_ownership_after_lease_expiry(self) -> None:
        task = self.worker_task()
        lease = task["runs"][0]["attempts"][0]["lease"]
        lease["acquired_at"] = "2026-07-13T11:00:00Z"
        lease["heartbeat_at"] = "2026-07-13T11:30:00Z"
        lease["last_progress_at"] = "2026-07-13T11:30:00Z"
        lease["expires_at"] = "2026-07-13T11:59:00Z"
        lease["liveness_state"] = "unknown"
        lease["monitor_gap_started_at"] = "2026-07-13T11:55:00Z"
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_worker_dispatch_requires_frozen_design(self) -> None:
        task = self.worker_task()
        task["dispatch"]["design_freeze"]["status"] = "draft"
        task["dispatch"]["design_freeze"]["frozen_at"] = None
        task["dispatch"]["design_freeze"]["fingerprint"] = None
        self.assert_invalid(task, "requires a frozen design before dispatch")

    def test_changed_design_requires_new_attempt(self) -> None:
        task = self.worker_task()
        task["dispatch"]["design_freeze"]["constraints"] = ["Use a different design."]
        task["dispatch"]["design_freeze"] = frozen_design() | {
            "constraints": ["Use a different design."]
        }
        payload = {
            key: task["dispatch"]["design_freeze"][key]
            for key in ("scope", "constraints", "acceptance", "change_policy")
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        task["dispatch"]["design_freeze"]["fingerprint"] = (
            f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        )
        self.assert_invalid(task, "a new Attempt is required")

    def test_heartbeat_coordinator_must_be_independent_from_worker(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat"]["coordinator_thread_id"] = task["runs"][0]["worker_id"]
        self.assert_invalid(task, "must differ from every Worker thread")

    def test_heartbeat_rejects_second_monitor_thread(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat"]["monitor_thread_id"] = "codex-thread:monitor-1"
        self.assert_invalid(task, "additional property is not allowed")

    def test_heartbeat_automation_prompt_has_hard_budget(self) -> None:
        task = self.worker_task()
        result = self.run_task(
            task,
            automation_status="ACTIVE",
            automation_prompt="x" * 221,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("maximum is 220", result.stderr)

    def test_heartbeat_automation_targets_dispatch_coordinator_thread(self) -> None:
        task = self.worker_task()
        result = self.run_task(
            task,
            automation_status="ACTIVE",
            automation_target_thread_id="codex-thread:wrong-monitor",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("differs from Automation target_thread_id", result.stderr)

    def test_incremental_heartbeat_rejects_non_ten_minute_interval(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat"]["interval_minutes"] = 5
        self.assert_invalid(task, "expected one of [10], got 5")

    def test_p0_incremental_heartbeat_uses_fixed_ten_minute_interval(self) -> None:
        task = self.worker_task()
        task["priority"] = "P0"
        task["display_name"] = "SPEC-101 P0 AA 新增页面"
        task["runs"][0]["worker_label"] = "SPEC-101 P0 AA 新增页面 [impl w01]"
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lease_risk_keeps_fixed_ten_minute_incremental_heartbeat(self) -> None:
        task = self.worker_task()
        task["runs"][0]["attempts"][0]["lease"]["expires_at"] = (
            "2026-07-13T12:10:00Z"
        )
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_blocked_recovery_keeps_fixed_ten_minute_incremental_heartbeat(self) -> None:
        task = self.worker_task()
        task["status"] = "ENV_BLOCKED"
        task["verification"]["status"] = "BLOCKED"
        task["blockers"] = [
            {
                "id": "env-001",
                "type": "environment",
                "status": "open",
                "description": "runtime unavailable",
                "owner": "pm",
                "hard": True,
                "cause": "external-unavailable",
                "recovery_attempts": 2,
                "next_unblock_action": "wait for runtime recovery",
                "opened_at": NOW,
                "resolved_at": None,
                "resolution": None,
            }
        ]
        evidence = base_evidence("SPEC-101")
        evidence["blockers"] = [
            {
                "id": "env-001",
                "type": "environment",
                "status": "open",
                "description": "runtime unavailable",
                "resolution": None,
            }
        ]
        evidence["conclusion"].update(
            {
                "status": "ENV_BLOCKED",
                "evidence_level": "NONE",
                "real_chain_verified": False,
            }
        )
        result = self.run_task(task, evidence)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_soft_blocker_cannot_move_task_to_blocked(self) -> None:
        task = self.worker_task()
        task["status"] = "ENV_BLOCKED"
        task["verification"]["status"] = "BLOCKED"
        task["blockers"] = [
            {
                "id": "env-soft-001",
                "type": "environment",
                "status": "open",
                "description": "first tool failure",
                "owner": "worker",
                "hard": False,
                "cause": "external-unavailable",
                "recovery_attempts": 0,
                "next_unblock_action": "retry in the same Worker",
                "opened_at": NOW,
                "resolved_at": None,
                "resolution": None,
            }
        ]
        self.assert_invalid(task, "requires an open hard blocker")

    def test_external_hard_blocker_requires_two_recovery_paths(self) -> None:
        task = self.worker_task()
        task["status"] = "ENV_BLOCKED"
        task["verification"]["status"] = "BLOCKED"
        task["blockers"] = [
            {
                "id": "env-hard-001",
                "type": "environment",
                "status": "open",
                "description": "external runtime unavailable",
                "owner": "worker",
                "hard": True,
                "cause": "external-unavailable",
                "recovery_attempts": 1,
                "next_unblock_action": "try the second recovery path",
                "opened_at": NOW,
                "resolved_at": None,
                "resolution": None,
            }
        ]
        self.assert_invalid(task, "at least two materially different recovery attempts")

    def test_visible_codex_worker_rejects_event_lease_without_heartbeat(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat_required"] = False
        task["dispatch"]["resolution"].update(
            {
                "monitor_mode": "event-lease",
                "capabilities": [
                    "background-worker",
                    "code-edit",
                    "git",
                    "lease-watchdog",
                    "milestone-notify",
                    "shell",
                    "terminal-event-wait",
                ],
            }
        )
        task["dispatch"]["heartbeat"] = None
        self.assert_invalid(task, "create_thread has no verified parent callback")

    def test_event_lease_requires_progress_timestamp(self) -> None:
        task = self.worker_task()
        task["dispatch"]["resolution"].update(
            {
                "monitor_mode": "event-lease",
                "capabilities": [
                    "background-worker",
                    "code-edit",
                    "git",
                    "lease-watchdog",
                    "milestone-notify",
                    "shell",
                    "terminal-event-wait",
                ],
            }
        )
        task["dispatch"]["heartbeat"] = None
        task["runs"][0]["attempts"][0]["lease"]["heartbeat_at"] = None
        self.assert_invalid(task, "requires lease.heartbeat_at")

    def test_event_lease_requires_persisted_progress_checkpoint(self) -> None:
        task = self.worker_task()
        task["dispatch"]["resolution"].update(
            {
                "monitor_mode": "event-lease",
                "capabilities": [
                    "background-worker",
                    "code-edit",
                    "git",
                    "lease-watchdog",
                    "milestone-notify",
                    "shell",
                    "terminal-event-wait",
                ],
            }
        )
        task["dispatch"]["heartbeat"] = None
        task["runs"][0]["attempts"][0]["lease"]["last_progress_summary"] = None
        self.assert_invalid(task, "requires a persisted progress checkpoint")

    def test_active_run_requires_active_heartbeat(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat"]["status"] = "paused"
        self.assert_invalid(task, "active runs require heartbeat.status=active")

    def test_codex_run_rejects_second_terminal_wait_authorization(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        events = [
            wait_event("snapshot-001", "status-observed", NOW),
            wait_event(
                "wait-auth-001",
                "terminal-wait-authorized",
                "2026-07-13T12:01:00Z",
            ),
            wait_event(
                "wait-auth-002",
                "terminal-wait-authorized",
                "2026-07-13T12:02:00Z",
            ),
        ]
        result = self.run_task(task, runtime=runtime, runtime_events=events)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("consumed 2 terminal waits", result.stderr)

    def test_heartbeat_cannot_authorize_positive_terminal_wait(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        events = [
            wait_event("snapshot-001", "status-observed", NOW),
            wait_event(
                "wait-auth-001",
                "terminal-wait-authorized",
                "2026-07-13T12:01:00Z",
                source="heartbeat",
            ),
        ]
        result = self.run_task(task, runtime=runtime, runtime_events=events)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cannot originate from Heartbeat", result.stderr)

    def test_codex_session_audit_rejects_unpermitted_native_wait(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[wait_event("snapshot-001", "status-observed", NOW)],
            codex_session_records=[
                native_wait_record("native-wait-001", "2026-07-13T12:01:00Z")
            ],
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unpermitted positive wait_threads", result.stderr)

    def test_codex_session_audit_accepts_one_authorized_native_wait(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[
                wait_event("snapshot-001", "status-observed", NOW),
                wait_event(
                    "wait-auth-001",
                    "terminal-wait-authorized",
                    "2026-07-13T12:00:30Z",
                ),
            ],
            codex_session_records=[
                native_wait_record("native-wait-001", "2026-07-13T12:01:00Z")
            ],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_codex_session_audit_rejects_unpermitted_zero_wait(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[],
            codex_session_records=[
                native_wait_record(
                    "native-inspect-001", "2026-07-13T12:01:00Z", timeout_ms=0
                )
            ],
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unpermitted zero-wait", result.stderr)

    def test_codex_session_audit_accepts_authorized_zero_wait(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[
                wait_event(
                    "inspect-auth-001",
                    "status-inspect-authorized",
                    "2026-07-13T12:00:30Z",
                )
            ],
            codex_session_records=[
                native_wait_record(
                    "native-inspect-001", "2026-07-13T12:01:00Z", timeout_ms=0
                )
            ],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validator_rejects_scheduled_inspections_inside_debounce(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[
                wait_event(
                    "inspect-auth-001",
                    "status-inspect-authorized",
                    "2026-07-13T12:00:00Z",
                ),
                wait_event(
                    "inspect-auth-002",
                    "status-inspect-authorized",
                    "2026-07-13T12:05:00Z",
                ),
            ],
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("less than 600 seconds", result.stderr)

    def test_validator_rejects_new_snapshot_after_unreconciled_authorization(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[
                wait_event(
                    "inspect-auth-001",
                    "status-inspect-authorized",
                    "2026-07-13T12:00:00Z",
                ),
                wait_event(
                    "inspect-auth-002",
                    "status-inspect-authorized",
                    "2026-07-13T12:10:00Z",
                ),
            ],
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("was not reconciled before another snapshot", result.stderr)

    def test_validator_debounces_scheduled_inspection_after_post_create(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        created = wait_event(
            "inspect-auth-created",
            "status-inspect-authorized",
            "2026-07-13T12:00:00Z",
        )
        created["payload"]["reason"] = "post-create"
        scheduled = wait_event(
            "inspect-auth-scheduled",
            "status-inspect-authorized",
            "2026-07-13T12:05:00Z",
        )
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[created, scheduled],
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("less than 600 seconds", result.stderr)

    def test_codex_session_audit_does_not_reuse_pre_policy_authorization(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[
                wait_event(
                    "wait-auth-old",
                    "terminal-wait-authorized",
                    "2026-07-13T11:59:00Z",
                ),
                wait_event("snapshot-001", "status-observed", NOW),
            ],
            codex_session_records=[
                native_wait_record("native-wait-001", "2026-07-13T12:01:00Z")
            ],
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unpermitted positive wait_threads", result.stderr)

    def test_terminal_wait_completion_must_match_authorization(self) -> None:
        task, runtime = split_runtime(self.worker_task())
        completion = wait_event(
            "wait-finished-001",
            "terminal-wait-finished",
            "2026-07-13T12:01:30Z",
        )
        completion["worker_id"] = "codex-thread:wrong-worker"
        result = self.run_task(
            task,
            runtime=runtime,
            runtime_events=[
                wait_event("snapshot-001", "status-observed", NOW),
                wait_event(
                    "wait-auth-001",
                    "terminal-wait-authorized",
                    "2026-07-13T12:01:00Z",
                ),
                completion,
            ],
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("must match authorization", result.stderr)

    def test_heartbeat_cannot_remain_active_without_active_run(self) -> None:
        task = self.worker_task()
        run = task["runs"][0]
        run.update({"status": "succeeded", "finished_at": NOW})
        run["attempts"][0].update({"status": "succeeded", "finished_at": NOW})
        self.assert_invalid(task, "heartbeat must be stopped or paused")

    def test_task_and_real_automation_status_must_match(self) -> None:
        task = self.worker_task()
        run = task["runs"][0]
        run.update({"status": "succeeded", "finished_at": NOW})
        run["attempts"][0].update({"status": "succeeded", "finished_at": NOW})
        task["dispatch"]["heartbeat"]["status"] = "paused"
        result = self.run_task(task, automation_status="ACTIVE")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("differs from Automation status active", result.stderr)

    def test_task_and_real_automation_interval_must_match(self) -> None:
        task = self.worker_task()
        result = self.run_task(
            task,
            automation_status="ACTIVE",
            automation_interval=5,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("differs from Automation interval 5", result.stderr)

    def test_dependency_cycle_is_rejected(self) -> None:
        first = base_task("SPEC-201")
        second = base_task("SPEC-202")
        for task, title in ((first, "依赖 A"), (second, "依赖 B")):
            task.update({"display_name": f"{task['id']} P1 AA {title}", "title": title, "type": "spec"})
            task["status"] = "READY_FOR_IMPL"
            task["lifecycle"]["phase"] = "implementation"
        first["dependencies"]["requires"] = [
            {"task_id": "SPEC-202", "required_status": "READY_FOR_IMPL", "source": "board", "evidence_ref": None}
        ]
        second["dependencies"]["requires"] = [
            {"task_id": "SPEC-201", "required_status": "READY_FOR_IMPL", "source": "board", "evidence_ref": None}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for task in (first, second):
                task_dir = Path(tmp) / task["id"]
                task_dir.mkdir()
                (task_dir / "task.yaml").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(VALIDATOR), "--tasks-dir", tmp, "--now", NOW],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dependency cycle", result.stderr)

    def test_active_lock_must_reference_active_run_and_expire(self) -> None:
        task = base_task()
        task["resources"]["locks"] = [
            {
                "resource_id": "repo:shared",
                "mode": "exclusive",
                "holder_run_id": "run-missing",
                "status": "active",
                "lease_expires_at": None,
                "scope": "write",
            }
        ]
        self.assert_invalid(task, "active resource lock requires lease_expires_at")

    def test_valid_codex_worker_passes(self) -> None:
        task = self.worker_task()
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unregistered_provider_is_rejected(self) -> None:
        task = self.worker_task()
        task["dispatch"]["provider_policy"] = {"mode": "pinned", "provider": "missing-provider"}
        task["dispatch"]["fallback_policy"]["allowed_providers"] = ["missing-provider"]
        task["dispatch"]["resolution"]["provider"] = "missing-provider"
        task["runs"][0]["provider"] = "missing-provider"
        self.assert_invalid(task, "has no registered adapter")

    def test_non_codex_machine_adapter_passes(self) -> None:
        task = self.worker_task()
        task["dispatch"].update(
            {
                "provider_policy": {"mode": "pinned", "provider": "external-cli"},
                "required_capabilities": ["background-worker", "code-edit", "git", "shell"],
                "heartbeat_required": False,
                "fallback_policy": {
                    "mode": "strict",
                    "allowed_providers": ["external-cli"],
                    "allow_manual_monitoring": True,
                },
                "resolution": {
                    "provider": "external-cli",
                    "adapter_version": "5",
                    "model_id": None,
                    "reasoning_profile": "standard",
                    "provider_reasoning_effort": "normal",
                    "worker_type": "agent-thread",
                    "monitor_mode": "poll",
                    "capabilities": ["background-worker", "code-edit", "git", "shell"],
                    "evidence_kinds": ["command", "log"],
                    "resolved_at": NOW,
                    "reason": "external adapter satisfies the generic request",
                },
                "heartbeat": None,
            }
        )
        task["runs"][0].update(
            {
                "worker_type": "agent-thread",
                "worker_id": "agent-thread:external-1",
                "provider": "external-cli",
                "adapter_version": "5",
                "model_id": None,
                "provider_reasoning_effort": "normal",
                "resolution_reason": "external adapter satisfies the generic request",
            }
        )
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compatible_policy_allows_fallback_from_pinned_provider(self) -> None:
        task = self.worker_task()
        task["dispatch"].update(
            {
                "provider_policy": {"mode": "pinned", "provider": "codex"},
                "required_capabilities": ["background-worker", "code-edit", "git", "shell"],
                "heartbeat_required": False,
                "fallback_policy": {
                    "mode": "compatible",
                    "allowed_providers": ["external-cli"],
                    "allow_manual_monitoring": True,
                },
                "resolution": {
                    "provider": "external-cli",
                    "adapter_version": "5",
                    "model_id": None,
                    "reasoning_profile": "standard",
                    "provider_reasoning_effort": "normal",
                    "worker_type": "agent-thread",
                    "monitor_mode": "poll",
                    "capabilities": ["background-worker", "code-edit", "git", "shell"],
                    "evidence_kinds": ["command", "log"],
                    "resolved_at": NOW,
                    "reason": "compatible fallback selected external-cli",
                },
                "heartbeat": None,
            }
        )
        task["runs"][0].update(
            {
                "worker_type": "agent-thread",
                "worker_id": "agent-thread:fallback-1",
                "provider": "external-cli",
                "adapter_version": "5",
                "model_id": None,
                "provider_reasoning_effort": "normal",
                "resolution_reason": "compatible fallback selected external-cli",
            }
        )
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_custom_adapter_worker_type_passes_end_to_end(self) -> None:
        adapter = json.loads(
            (ROOT / "references" / "adapters" / "external-cli.adapter.json").read_text(
                encoding="utf-8"
            )
        )
        adapter["worker_types"] = ["crew-worker"]
        task = self.worker_task()
        task["dispatch"].update(
            {
                "provider_policy": {"mode": "pinned", "provider": "external-cli"},
                "required_capabilities": ["background-worker", "code-edit", "git", "shell"],
                "heartbeat_required": False,
                "fallback_policy": {
                    "mode": "strict",
                    "allowed_providers": ["external-cli"],
                    "allow_manual_monitoring": True,
                },
                "resolution": {
                    "provider": "external-cli",
                    "adapter_version": "5",
                    "model_id": None,
                    "reasoning_profile": "standard",
                    "provider_reasoning_effort": "normal",
                    "worker_type": "crew-worker",
                    "monitor_mode": "poll",
                    "capabilities": ["background-worker", "code-edit", "git", "shell"],
                    "evidence_kinds": ["command", "log"],
                    "resolved_at": NOW,
                    "reason": "custom worker transport",
                },
                "heartbeat": None,
            }
        )
        task["runs"][0].update(
            {
                "worker_type": "crew-worker",
                "worker_id": "crew-worker:one",
                "provider": "external-cli",
                "adapter_version": "5",
                "model_id": None,
                "provider_reasoning_effort": "normal",
                "resolution_reason": "custom worker transport",
            }
        )
        result = self.run_task(task, adapters=[adapter])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_resolution_keeps_generic_and_provider_reasoning_separate(self) -> None:
        task = self.worker_task()
        task["dispatch"]["reasoning_profile"] = "deep"
        task["dispatch"]["resolution"]["reasoning_profile"] = "deep"
        task["dispatch"]["resolution"]["provider_reasoning_effort"] = "high"
        task["runs"][0]["reasoning_profile"] = "deep"
        task["runs"][0]["provider_reasoning_effort"] = "high"
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_codex_model_override_is_rejected(self) -> None:
        task = self.worker_task()
        task["dispatch"]["resolution"]["model_id"] = "forbidden-model"
        self.assert_invalid(task, "does not declare model routing")

    def test_terminal_historical_run_keeps_original_model_metadata(self) -> None:
        task = self.worker_task()
        run = task["runs"][0]
        run["status"] = "succeeded"
        run["finished_at"] = "2026-07-13T12:30:00Z"
        run["attempts"][0]["status"] = "succeeded"
        run["attempts"][0]["finished_at"] = "2026-07-13T12:30:00Z"
        run["model_id"] = "host-default"
        task["dispatch"]["heartbeat"]["status"] = "stopped"
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compatible_manual_monitor_fallback_passes(self) -> None:
        task = self.worker_task()
        task["dispatch"].update(
            {
                "provider_policy": {"mode": "pinned", "provider": "external-cli"},
                "fallback_policy": {
                    "mode": "compatible",
                    "allowed_providers": ["external-cli"],
                    "allow_manual_monitoring": True,
                },
                "resolution": {
                    "provider": "external-cli",
                    "adapter_version": "5",
                    "model_id": None,
                    "reasoning_profile": "standard",
                    "provider_reasoning_effort": "normal",
                    "worker_type": "agent-thread",
                    "monitor_mode": "manual",
                    "capabilities": ["background-worker", "code-edit", "git", "shell"],
                    "evidence_kinds": ["command", "log"],
                    "resolved_at": NOW,
                    "reason": "compatible manual monitoring fallback",
                },
                "heartbeat": None,
            }
        )
        task["runs"][0].update(
            {
                "worker_type": "agent-thread",
                "worker_id": "agent-thread:manual-1",
                "provider": "external-cli",
                "adapter_version": "5",
                "model_id": None,
                "provider_reasoning_effort": "normal",
                "resolution_reason": "compatible manual monitoring fallback",
            }
        )
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_run_must_match_dispatch_resolution(self) -> None:
        task = self.worker_task()
        task["runs"][0]["reasoning_profile"] = "deep"
        self.assert_invalid(task, "reasoning_profile differs from dispatch resolution")

    def test_resolution_must_cover_required_evidence_kinds(self) -> None:
        task = self.worker_task()
        task["dispatch"]["required_evidence_kinds"].append("browser")
        self.assert_invalid(task, "evidence_kinds do not cover required_evidence_kinds")

    def test_nonterminal_task_can_record_failed_gate_artifact(self) -> None:
        evidence = base_evidence()
        evidence["artifacts"]["browser"] = [
            {**artifact("browser", "browser-001"), "result": "fail"}
        ]
        result = self.run_task(base_task(), evidence)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_terminal_gate_rejects_reference_to_failed_artifact(self) -> None:
        task = base_task("SPEC-042")
        task.update(
            {
                "display_name": "SPEC-042 P1 WEB 新增页面",
                "title": "新增页面",
                "type": "spec",
                "area": ["WEB"],
                "status": "VERIFIED",
            }
        )
        task["lifecycle"]["phase"] = "closure"
        task["closure"]["status"] = "ready"
        task["verification"].update({"required_levels": ["L3"], "status": "L3_VERIFIED"})
        evidence = base_evidence("SPEC-042")
        evidence["verification"]["changed_surface"] = ["ui page"]
        evidence["verification"]["levels"] = {
            "L3": {
                "status": "pass",
                "summary": "browser flow failed",
                "evidence_refs": ["browser-001"],
            }
        }
        evidence["artifacts"]["browser"] = [
            {**artifact("browser", "browser-001"), "result": "fail"}
        ]
        self.assert_invalid(task, "references non-passing artifact", evidence)

    def test_batch_worker_requires_two_to_four_task_ids(self) -> None:
        task = self.worker_task()
        task["dispatch"]["strategy"] = "batch-worker"
        task["dispatch"]["batch"] = {
            "batch_id": "BATCH-AA",
            "display_name": "BATCH-AA P1 AA 批量实现",
            "task_ids": ["SPEC-101"],
        }
        self.assert_invalid(task, "expected at least 2 items")

    def worker_task(self) -> dict:
        task = base_task("SPEC-101")
        task.update({"display_name": "SPEC-101 P1 AA 新增页面", "title": "新增页面", "type": "spec"})
        task["status"] = "IN_IMPL"
        task["lifecycle"]["phase"] = "implementation"
        task["dispatch"] = codex_dispatch()
        task["runs"] = [codex_run()]
        return task


if __name__ == "__main__":
    unittest.main()

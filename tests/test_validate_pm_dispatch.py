from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_pm_dispatch.py"
NOW = "2026-07-13T12:00:00Z"


def base_task(task_id: str = "BUG-041") -> dict:
    return {
        "schema_version": "2",
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
            "model_request": None,
            "fallback_policy": None,
            "resolution": None,
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
        "provider": "codex",
        "adapter_version": "1",
        "model_id": "gpt-5.6-sol",
        "reasoning_profile": "standard",
        "provider_reasoning_effort": "medium",
        "resolution_reason": "normal task",
        "status": "running",
        "allow_parallel": index > 1,
        "started_at": NOW,
        "finished_at": None,
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
        "model_request": {
            "quality": "frontier",
            "reasoning_profile": "standard",
            "latency": "normal",
            "cost": "balanced",
        },
        "fallback_policy": {
            "mode": "strict",
            "allowed_providers": ["codex"],
            "allow_model_substitution": False,
            "allow_manual_monitoring": False,
        },
        "resolution": {
            "provider": "codex",
            "adapter_version": "1",
            "model_id": "gpt-5.6-sol",
            "reasoning_profile": "standard",
            "provider_reasoning_effort": "medium",
            "worker_type": "codex-thread",
            "monitor_mode": "heartbeat",
            "capabilities": ["background-worker", "code-edit", "git", "heartbeat", "shell"],
            "evidence_kinds": ["command", "log"],
            "resolved_at": NOW,
            "reason": "pinned provider satisfies the requested capabilities",
        },
        "batch": None,
        "heartbeat": {
            "automation_id": "automation-001",
            "interval_minutes": 15,
            "max_checks": 6,
            "stop_condition": "run terminal",
            "lightweight": True,
            "status": "active",
        },
        "escalation_triggers": [],
    }


class ValidatorCase(unittest.TestCase):
    def run_task(
        self,
        task: dict,
        evidence: dict | None = None,
        adapters: list[dict] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / task["id"]
            task_dir.mkdir()
            task_path = task_dir / "task.json"
            task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
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

    def test_duplicate_attempt_id_is_rejected(self) -> None:
        task = self.worker_task()
        task["runs"][0]["attempts"].append(copy.deepcopy(task["runs"][0]["attempts"][0]))
        self.assert_invalid(task, "duplicate attempt_id")

    def test_max_parallel_workers_is_enforced(self) -> None:
        task = self.worker_task()
        task["dispatch"]["strategy"] = "full-dispatch"
        task["runs"].append(codex_run(index=2))
        self.assert_invalid(task, "max_parallel_workers=1")

    def test_heartbeat_required_needs_automation_metadata(self) -> None:
        task = self.worker_task()
        task["dispatch"]["heartbeat"] = None
        self.assert_invalid(task, "heartbeat metadata")

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
                    "allow_model_substitution": False,
                    "allow_manual_monitoring": True,
                },
                "resolution": {
                    "provider": "external-cli",
                    "adapter_version": "1",
                    "model_id": "external-frontier",
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
                "adapter_version": "1",
                "model_id": "external-frontier",
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
                    "allow_model_substitution": False,
                    "allow_manual_monitoring": True,
                },
                "resolution": {
                    "provider": "external-cli",
                    "adapter_version": "1",
                    "model_id": "external-frontier",
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
                "model_id": "external-frontier",
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
                    "allow_model_substitution": False,
                    "allow_manual_monitoring": True,
                },
                "resolution": {
                    "provider": "external-cli",
                    "adapter_version": "1",
                    "model_id": "external-frontier",
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
                "model_id": "external-frontier",
                "provider_reasoning_effort": "normal",
                "resolution_reason": "custom worker transport",
            }
        )
        result = self.run_task(task, adapters=[adapter])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_resolution_keeps_generic_and_provider_reasoning_separate(self) -> None:
        task = self.worker_task()
        task["dispatch"]["model_request"]["reasoning_profile"] = "deep"
        task["dispatch"]["resolution"]["reasoning_profile"] = "deep"
        task["dispatch"]["resolution"]["provider_reasoning_effort"] = "high"
        task["runs"][0]["reasoning_profile"] = "deep"
        task["runs"][0]["provider_reasoning_effort"] = "high"
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_frontier_model_satisfies_balanced_quality_request(self) -> None:
        task = self.worker_task()
        task["dispatch"]["model_request"]["quality"] = "balanced"
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
                    "allow_model_substitution": False,
                    "allow_manual_monitoring": True,
                },
                "resolution": {
                    "provider": "external-cli",
                    "adapter_version": "1",
                    "model_id": "external-frontier",
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
                "adapter_version": "1",
                "model_id": "external-frontier",
                "provider_reasoning_effort": "normal",
                "resolution_reason": "compatible manual monitoring fallback",
            }
        )
        result = self.run_task(task)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_run_must_match_dispatch_resolution(self) -> None:
        task = self.worker_task()
        task["runs"][0]["model_id"] = "different-model"
        self.assert_invalid(task, "model_id differs from dispatch resolution")

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

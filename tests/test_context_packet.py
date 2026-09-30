from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_validate_pm_dispatch import (
    base_task,
    codex_dispatch,
    codex_run,
    split_runtime,
)


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_context_packet.py"
SCHEMA_PATH = ROOT / "references" / "schemas" / "context-packet.schema.json"
NOW = "2026-08-27T00:00:00Z"


def load_builder():
    spec = importlib.util.spec_from_file_location("pm_context_builder", BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def task_fixture() -> dict:
    return {
        "schema_version": "3",
        "id": "SPEC-042",
        "display_name": "SPEC-042 P1 PM 精益上下文",
        "title": "精益上下文",
        "type": "spec",
        "priority": "P1",
        "status": "TRIAGED",
        "mode": "single-project",
        "area": ["PM"],
        "lifecycle": {
            "phase": "triage",
            "owner": "PM",
            "accepted_scope": "生成紧凑的 Worker 上下文",
            "next_action": "实现 Context Packet",
        },
        "verification": {
            "required_levels": ["L1"],
            "gate_policy": "default",
            "evidence_file": "evidence.json",
            "status": "PENDING",
            "mock_allowed": False,
            "missing": ["Context Packet 聚焦测试"],
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
            "reason": "本地确定性工具",
            "worker_required": False,
            "heartbeat_required": False,
            "selected_at": NOW,
            "max_parallel_workers": None,
            "reasoning_profile": None,
            "fallback_policy": None,
            "resolution": None,
            "autonomy_policy": {
                "default_action": "proceed",
                "clarification_policy": "material-irreversible-only",
                "blocker_policy": "hard-only",
                "verification_policy": "risk-scaled",
                "recovery": {
                    "same_method_retries": 1,
                    "alternate_method_attempts": 2,
                    "rediscovery_limit": 1,
                },
            },
            "design_freeze": None,
            "worker_reuse": None,
            "batch": None,
            "heartbeat": None,
            "escalation_triggers": [],
        },
        "runs": [],
        "last_updated": NOW,
    }


def evidence_fixture() -> dict:
    return {
        "schema_version": "2",
        "task_id": "SPEC-042",
        "generated_at": NOW,
        "verification": {
            "changed_surface": ["pm-context"],
            "original_user_path": "PM 分发 Worker",
            "runtime_shape": "dev",
            "test_data": [],
            "levels": {
                "L0": {
                    "status": "pass",
                    "summary": "Schema 已验证",
                    "evidence_refs": ["command-001"],
                    "commands": ["python3 -m unittest"],
                }
            },
            "existing_data_regression": "not changed",
            "uncovered_items": [],
        },
        "quality_checks": [
            {
                "id": "unit-test",
                "status": "passed",
                "tool": "unittest",
                "summary": "聚焦测试通过",
                "evidence_refs": ["command-001"],
                "skip_reason": None,
                "checked_at": NOW,
            }
        ],
        "artifacts": {
            "commands": [
                {
                    "artifact_id": "command-001",
                    "kind": "command",
                    "source": "unittest",
                    "subject": "context packet",
                    "result": "pass",
                    "captured_at": NOW,
                    "evidence_ref": "evidence/command-001.json",
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
            "evidence_level": "L0",
            "mock_based": False,
            "real_chain_verified": False,
            "accepted_fallback": None,
        },
    }


class ContextPacketCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.builder = load_builder()
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def create_sources(self, root: Path) -> tuple[Path, Path]:
        task_path = root / "task.json"
        evidence_path = root / "evidence.json"
        task_path.write_text(
            json.dumps(task_fixture(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        evidence_path.write_text(
            json.dumps(evidence_fixture(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return task_path, evidence_path

    def test_packet_is_compact_and_hash_is_stable_across_generation_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _ = self.create_sources(root)
            output = root / "context" / "active-context.json"
            first, first_text = self.builder.build_context_packet(
                task_path, output, generated_at=NOW
            )
            second, second_text = self.builder.build_context_packet(
                task_path, output, generated_at="2026-08-27T00:05:00Z"
            )
            self.assertEqual(first["packet_sha256"], second["packet_sha256"])
            self.assertLessEqual(len(first_text), 8000)
            self.assertLessEqual(len(second_text), 8000)
            self.assertEqual(first["objective"], "生成紧凑的 Worker 上下文")
            self.assertEqual(first["confirmed_facts"][0]["status"], "pass")

    def test_packet_carries_thin_wrapper_delegation_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _ = self.create_sources(root)
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["dispatch"]["delegation"] = {
                "mode": "thin-wrapper-subagent",
                "agent": "external-agent-test",
                "initial_invocation_limit": 1,
                "repair_invocation_limit": 1,
                "retry_policy": "focused-verification-failure-only",
            }
            task_path.write_text(
                json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            output = root / "context" / "active-context.json"
            packet, _ = self.builder.build_context_packet(
                task_path, output, generated_at=NOW
            )
            self.assertEqual(
                packet["execution"]["delegation"], task["dispatch"]["delegation"]
            )

    def test_validator_rejects_source_drift_and_unapproved_full_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _ = self.create_sources(root)
            output = root / "context" / "active-context.json"
            packet, rendered = self.builder.build_context_packet(
                task_path, output, generated_at=NOW
            )
            errors = self.builder.validate_context_packet(
                packet,
                packet_path=output,
                schema=self.schema,
                packet_text=rendered,
                prompt_text="请完整读取 Task、Evidence 和全部历史后继续。",
                prompt_mode="initial",
                check_sources=True,
            )
            self.assertTrue(any("without an allowed trigger" in item for item in errors))

            task_data = task_fixture()
            task_data["title"] = "已漂移"
            task_path.write_text(
                json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            drift_errors = self.builder.validate_context_packet(
                packet,
                packet_path=output,
                schema=self.schema,
                packet_text=rendered,
                check_sources=True,
            )
            self.assertTrue(any("source digest drift" in item for item in drift_errors))

    def test_explicit_forensic_trigger_allows_full_read_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _ = self.create_sources(root)
            output = root / "context" / "active-context.json"
            packet, rendered = self.builder.build_context_packet(
                task_path,
                output,
                generated_at=NOW,
                full_read_trigger="forensic-diagnosis",
            )
            errors = self.builder.validate_context_packet(
                packet,
                packet_path=output,
                schema=self.schema,
                packet_text=rendered,
                prompt_text="为取证完整读取 Task、Evidence 和历史。",
                check_sources=True,
            )
            self.assertEqual(errors, [])

    def test_runtime_lease_churn_and_output_path_do_not_change_packet_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = base_task("SPEC-101")
            task.update({"status": "IN_IMPL", "type": "spec"})
            task["lifecycle"]["phase"] = "implementation"
            task["dispatch"] = codex_dispatch()
            task["runs"] = [codex_run()]
            task, runtime = split_runtime(task)
            task_path = root / "task.json"
            runtime_path = root / "runtime.yaml"
            task_path.write_text(json.dumps(task), encoding="utf-8")
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")

            first, _ = self.builder.build_context_packet(
                task_path, root / "first" / "active-context.json", generated_at=NOW
            )
            lease = runtime["runs"][0]["attempts"][0]["lease"]
            lease["heartbeat_at"] = "2026-08-27T00:10:00Z"
            lease["expires_at"] = "2026-08-27T01:10:00Z"
            lease["renew_count"] = 1
            lease["event_cursor"] = "cursor-2"
            runtime["runs"][0]["event_cursor"] = "cursor-2"
            runtime["last_updated"] = "2026-08-27T00:10:00Z"
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
            second, _ = self.builder.build_context_packet(
                task_path,
                root / "second" / "active-context.json",
                generated_at="2026-08-27T00:10:00Z",
            )
            self.assertEqual(first["packet_sha256"], second["packet_sha256"])
            self.assertEqual(
                second["source_digests"]["runtime"]["digest_kind"],
                "runtime-context-v1",
            )

            lease["last_progress_summary"] = "core edit complete"
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
            drift = self.builder.validate_context_packet(
                second,
                packet_path=root / "second" / "active-context.json",
                schema=self.schema,
                check_sources=True,
            )
            self.assertTrue(any("runtime source digest drift" in item for item in drift))

    def test_project_snapshot_source_identity_ignores_absolute_root(self) -> None:
        snapshot = {
            "schema_version": "1",
            "root": "/workspace/one",
            "generated_at": NOW,
            "snapshot_sha256": "sha256:" + "0" * 64,
            "git": {"head": "abc", "status_sha256": "sha256:" + "1" * 64},
            "focus": [],
        }
        relocated = dict(snapshot, root="/workspace/two")
        first = self.builder.source_sha256(
            Path("unused"), self.builder.PROJECT_SNAPSHOT_V1, snapshot
        )
        second = self.builder.source_sha256(
            Path("unused"), self.builder.PROJECT_SNAPSHOT_V1, relocated
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

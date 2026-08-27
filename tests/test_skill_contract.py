from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractCase(unittest.TestCase):
    def test_task_panel_uses_fixed_decision_columns(self) -> None:
        panel = (ROOT / "references" / "task-panel.md").read_text(encoding="utf-8")
        self.assertIn("| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |", panel)

    def test_task_panel_keeps_runtime_metadata_out_of_main_view(self) -> None:
        panel = (ROOT / "references" / "task-panel.md").read_text(encoding="utf-8")
        self.assertIn("主面板不展示 Owner、Worker、Run、Lease 或 Adapter", panel)
        self.assertIn("<id> <title>", panel)

    def test_main_skill_stays_within_context_budget(self) -> None:
        skill = (ROOT / "SKILL.md").read_bytes()
        self.assertLessEqual(len(skill), 5500)

    def test_fast_execution_principles_are_explicit(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "最低足够的模型/effort",
            "无新证据，不新增探索或重复检查",
            "证据足够后立即实施",
            "只验正确性关键路径和必要回归",
            "不为无证据的未来风险扩围",
            "关键验证通过且无新证据即停",
        ):
            self.assertIn(phrase, skill)

    def test_progressive_disclosure_keeps_details_out_of_main_skill(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("不要把 JSON 加载进上下文", skill)
        self.assertNotIn("| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |", skill)
        for name in (
            "autonomy.md",
            "closure.md",
            "prompts.md",
            "task-examples.md",
            "task-panel.md",
        ):
            self.assertIn(f"references/{name}", skill)
            self.assertTrue((ROOT / "references" / name).is_file())

    def test_task_does_not_accept_user_model_selection(self) -> None:
        task_schema = (
            ROOT / "references" / "schemas" / "task.schema.json"
        ).read_text(encoding="utf-8")
        adapter_schema = (
            ROOT / "references" / "schemas" / "adapter.schema.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"model_request"', task_schema)
        self.assertIn('"model_id"', task_schema)
        self.assertIn('"model"', adapter_schema)
        self.assertNotIn('"model_request"', adapter_schema)

    def test_codex_workers_use_dispatch_host_default_model(self) -> None:
        adapter = (ROOT / "references" / "adapters" / "codex.adapter.json").read_text(
            encoding="utf-8"
        )
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn('"gpt-5.6-luna"', adapter)
        self.assertNotIn('"gpt-5.6-sol"', adapter)
        self.assertNotIn('"model": {', adapter)
        self.assertIn('"input_fields": ["title", "prompt"]', adapter)
        self.assertIn('"optional_input_fields": ["reasoning_effort"]', adapter)
        self.assertIn("跟随发布端的 Codex 默认模型配置", skill)

    def test_monitoring_uses_ten_minute_coordinator_heartbeat(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        schema = (ROOT / "references" / "schemas" / "task.schema.json").read_text(
            encoding="utf-8"
        )
        validator = (ROOT / "scripts" / "validate_pm_dispatch.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("分发任务线程每 10 分钟", skill)
        self.assertIn("不得再创建独立监控 Worker/任务", skill)
        self.assertIn("增量检查", skill)
        self.assertIn('"scan_scope"', schema)
        self.assertIn('"incremental"', schema)
        self.assertIn('"read_set"', schema)
        self.assertNotIn('"monitor_thread_id"', schema)
        self.assertIn('"context_policy": {"type": "string", "enum": ["coordinator"]}', schema)
        self.assertIn('"interval_minutes": {"type": "integer", "enum": [10]}', schema)
        self.assertIn("COORDINATOR_HEARTBEAT_INTERVAL_MINUTES = 10", validator)
        self.assertIn("HEARTBEAT_PROMPT_MAX_CHARS = 240", validator)

    def test_cross_file_protocol_consistency(self) -> None:
        result = subprocess.run(
            ["python3", str(ROOT / "scripts" / "validate_skill_consistency.py")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        core = (ROOT / "references" / "core-contract.md").read_text(encoding="utf-8")
        self.assertNotIn("every 5 minutes", core)
        self.assertNotIn("exactly 5 minutes", core)

    def test_task_runtime_contract_is_split_and_versioned(self) -> None:
        task_schema = json.loads(
            (ROOT / "references" / "schemas" / "task.schema.json").read_text(
                encoding="utf-8"
            )
        )
        runtime_schema = json.loads(
            (ROOT / "references" / "schemas" / "runtime.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("4", task_schema["properties"]["schema_version"]["enum"])
        self.assertIn("runtime_file", task_schema["properties"])
        self.assertEqual(
            runtime_schema["properties"]["schema_version"]["enum"], ["1"]
        )
        self.assertIn("continuation_token", runtime_schema["$defs"]["run"]["properties"])
        self.assertIn("event_log_file", runtime_schema["required"])

    def test_dispatch_design_is_frozen_before_worker_runs(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        schema = (ROOT / "references" / "schemas" / "task.schema.json").read_text(
            encoding="utf-8"
        )
        validator = (ROOT / "scripts" / "validate_pm_dispatch.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("只有安全边界或受保护的冻结设计指纹变化", skill)
        self.assertIn("普通可恢复问题留在同一 Worker/Attempt", skill)
        self.assertIn('"design_freeze"', schema)
        self.assertIn('"design_fingerprint"', schema)
        self.assertIn("a new Attempt is required", validator)

    def test_quality_checks_are_machine_validated_without_new_lifecycle(self) -> None:
        task_schema = json.loads(
            (ROOT / "references" / "schemas" / "task.schema.json").read_text(
                encoding="utf-8"
            )
        )
        evidence_schema = (
            ROOT / "references" / "schemas" / "evidence.schema.json"
        ).read_text(encoding="utf-8")
        validator = (ROOT / "scripts" / "validate_pm_dispatch.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("quality_checks", task_schema["required"])
        self.assertIn("requirement", task_schema["properties"]["quality_checks"]["properties"]["checks"]["items"]["properties"])
        self.assertIn('"quality_checks"', evidence_schema)
        self.assertIn("def validate_quality_checks", validator)
        self.assertIn("closure requires at least one required quality check", validator)
        self.assertEqual(
            task_schema["properties"]["lifecycle"]["properties"]["phase"]["enum"],
            [
                "intake",
                "triage",
                "contract",
                "implementation",
                "integration",
                "verification",
                "closure",
                "archive",
            ],
        )

    def test_skill_defaults_to_autonomy_and_terminal_delegation(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        autonomy = (ROOT / "references" / "autonomy.md").read_text(encoding="utf-8")
        prompts = (ROOT / "references" / "prompts.md").read_text(encoding="utf-8")
        self.assertIn("只有硬 Blocker 才停止", skill)
        self.assertIn("首次命令、构建或测试失败不是 Blocker", skill)
        self.assertIn("终态 delegation", prompts)
        self.assertIn("Event-Lease Watchdog", prompts)
        self.assertIn("宽限后再探测一次", prompts)
        schema = (ROOT / "references" / "schemas" / "task.schema.json").read_text(
            encoding="utf-8"
        )
        self.assertIn('"progress_seq"', schema)
        self.assertIn('"last_progress_summary"', schema)
        self.assertIn('"event_cursor"', schema)
        self.assertIn('"disconnect_probe_count"', schema)
        self.assertIn('"liveness_state"', schema)
        self.assertIn('"monitor_gap_started_at"', schema)
        self.assertIn("首次命令、构建、测试或工具失败不是 Blocker", autonomy)

    def test_heartbeat_prompt_template_fits_default_budget(self) -> None:
        prompts = (ROOT / "references" / "prompts.md").read_text(encoding="utf-8")
        heartbeat = prompts.split("## Heartbeat", 1)[1]
        heartbeat = heartbeat.split("```markdown\n", 1)[1].split("\n```", 1)[0]
        self.assertLessEqual(len(heartbeat), 220)
        self.assertIn("增量检查", heartbeat)

    def test_single_worker_reuse_and_cache_prefix_are_explicit(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompts = (ROOT / "references" / "prompts.md").read_text(encoding="utf-8")
        schema = (ROOT / "references" / "schemas" / "task.schema.json").read_text(
            encoding="utf-8"
        )
        validator = (ROOT / "scripts" / "validate_pm_dispatch.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("任务级粘性 Worker", skill)
        self.assertIn("稳定执行契约", prompts)
        self.assertIn("动态任务后缀", prompts)
        self.assertIn('"worker_reuse"', schema)
        self.assertIn('"worker_replacement_reason"', schema)
        self.assertIn("requires sticky reuse across gates", validator)

    def test_context_packet_is_the_default_worker_injection_contract(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompts = (ROOT / "references" / "prompts.md").read_text(encoding="utf-8")
        context_schema = json.loads(
            (ROOT / "references" / "schemas" / "context-packet.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("Context Packet", skill)
        self.assertIn("Context Packet", prompts)
        self.assertEqual(context_schema["properties"]["schema_version"]["enum"], ["1"])
        self.assertTrue(
            {
                "task",
                "execution",
                "confirmed_facts",
                "source_digests",
                "packet_sha256",
            }.issubset(set(context_schema["required"]))
        )


if __name__ == "__main__":
    unittest.main()

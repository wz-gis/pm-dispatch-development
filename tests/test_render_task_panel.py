from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER_PATH = ROOT / "scripts" / "render_task_panel.py"
SNAPSHOT_PATH = ROOT / "tests" / "snapshots" / "task_panel.md"


def load_renderer():
    spec = importlib.util.spec_from_file_location("pm_task_panel", RENDERER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def task(task_id: str, title: str, priority: str, status: str, next_action: str) -> dict:
    return {
        "id": task_id,
        "title": title,
        "priority": priority,
        "status": status,
        "lifecycle": {"next_action": next_action},
        "blockers": [],
    }


class TaskPanelCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.renderer = load_renderer()

    def test_every_task_schema_status_has_a_panel_label(self) -> None:
        schema = json.loads(
            (ROOT / "references" / "schemas" / "task.schema.json").read_text(
                encoding="utf-8"
            )
        )
        statuses = set(schema["properties"]["status"]["enum"])
        self.assertEqual(set(self.renderer.STATUS_LABELS), statuses)

    def test_panel_matches_snapshot(self) -> None:
        in_progress = task(
            "BUG-001", "分页结果缺失", "P1", "IN_IMPL", "补充 API 验收证据"
        )
        blocked = task(
            "BUG-002",
            "设置保存失败",
            "P0",
            "ENV_BLOCKED",
            "恢复测试服务后补页面验收",
        )
        blocked["blockers"] = [
            {
                "status": "open",
                "description": "代码与构建通过；测试服务不可用",
            }
        ]
        pending = task(
            "SPEC-003", "设置页面", "P1", "NEW", "确认页面范围和验收项"
        )
        partial = task(
            "SPEC-004", "文件上传", "P1", "PARTIAL_VERIFIED", "补充真实上传路径验收"
        )
        items = [
            (
                in_progress,
                {
                    "verification": {
                        "levels": {
                            "L2": {
                                "status": "pass",
                                "summary": "分页回归测试已通过",
                            }
                        }
                    }
                },
            ),
            (partial, {"verification": {"levels": {"L3": {"status": "pass_mock", "summary": "Mock L3 已通过"}}}}),
            (pending, None),
            (blocked, None),
        ]
        rendered = self.renderer.render_task_panel(items)
        self.assertEqual(rendered, SNAPSHOT_PATH.read_text(encoding="utf-8").rstrip("\n"))

    def test_closed_tasks_are_hidden_by_default(self) -> None:
        closed = task("BUG-099", "已关闭任务", "P0", "CLOSED", "none")
        rendered = self.renderer.render_task_panel([(closed, None)])
        self.assertNotIn("BUG-099", rendered)

    def test_actionable_view_hides_verified_and_limits_rows(self) -> None:
        items = [
            (task(f"SPEC-{index:03d}", f"任务 {index}", "P1", "NEW", "执行"), None)
            for index in range(1, 11)
        ]
        items.append((task("SPEC-099", "已验证", "P0", "VERIFIED", "none"), None))
        rendered = self.renderer.render_task_panel(items)
        self.assertNotIn("SPEC-099", rendered)
        self.assertIn("另有 2 项", rendered)
        self.assertNotIn("SPEC-009", rendered)

    def test_waiting_user_view_uses_hard_human_gate(self) -> None:
        waiting = task("SPEC-042", "人工授权", "P0", "ENV_BLOCKED", "等待用户")
        waiting["blockers"] = [
            {
                "status": "open",
                "hard": True,
                "cause": "human-authorization",
                "description": "等待用户本人完成授权",
            }
        ]
        other = task("SPEC-043", "环境修复", "P0", "ENV_BLOCKED", "修环境")
        rendered = self.renderer.render_task_panel(
            [(waiting, None), (other, None)], view="waiting-user"
        )
        self.assertIn("SPEC-042", rendered)
        self.assertNotIn("SPEC-043", rendered)

    def test_verified_release_is_rolled_up_into_parent(self) -> None:
        parent = task("SPEC-042", "父任务", "P1", "READY_FOR_CLOSURE", "收口")
        release = task("RELEASE-042", "发布父任务", "P1", "VERIFIED", "none")
        release["type"] = "release"
        release["dependencies"] = {
            "requires": [{"task_id": "SPEC-042"}],
        }
        rendered = self.renderer.render_task_panel([(parent, None), (release, None)])
        self.assertIn("发布 RELEASE-042 已收口", rendered)
        self.assertNotIn("RELEASE-042 发布父任务", rendered)

    def test_all_view_can_include_closed_without_default_budget(self) -> None:
        closed = task("BUG-099", "已关闭任务", "P0", "CLOSED", "none")
        rendered = self.renderer.render_task_panel(
            [(closed, None)], view="all", limit=None, max_chars=None
        )
        self.assertIn("BUG-099", rendered)

    def test_task_lookup_bypasses_default_view(self) -> None:
        verified = task("SPEC-099", "已验证任务", "P1", "VERIFIED", "none")
        rendered = self.renderer.render_task_panel(
            [(verified, None)], task_id="SPEC-099"
        )
        self.assertIn("SPEC-099", rendered)

    def test_writes_reusable_delegated_read_snapshot(self) -> None:
        rendered = self.renderer.render_task_panel(
            [(task("SPEC-042", "父任务", "P1", "READY_FOR_IMPL", "实施"), None)]
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "task-panel.md"
            metadata = self.renderer.write_panel_snapshot(
                output, rendered, "actionable", None
            )
            self.assertEqual(metadata["mode"], "delegated-read")
            self.assertEqual(metadata["chars"], len(rendered))
            self.assertTrue(metadata["sha256"].startswith("sha256:"))
            self.assertEqual(output.read_text(encoding="utf-8").rstrip("\n"), rendered)


if __name__ == "__main__":
    unittest.main()

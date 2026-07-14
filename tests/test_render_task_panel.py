from __future__ import annotations

import importlib.util
import json
import sys
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
            "BUG-041", "最近诊断记录", "P1", "IN_IMPL", "补 API/性能证据，再执行 L3/L4"
        )
        blocked = task(
            "BUG-033",
            "规则保存启用与描述提取",
            "P0",
            "ENV_BLOCKED",
            "修复服务类加载环境后补 API/页面验收",
        )
        blocked["blockers"] = [
            {
                "status": "open",
                "description": "代码已修复，构建通过；服务类加载环境仍失败",
            }
        ]
        pending = task(
            "SPEC-004", "跨工程堆栈优先诊断", "P1", "NEW", "明确搜索范围、排序和权限"
        )
        partial = task(
            "SPEC-001", "ZIP 源码包接入", "P1", "PARTIAL_VERIFIED", "补真实内网 ZIP L4"
        )
        items = [
            (
                in_progress,
                {
                    "verification": {
                        "levels": {
                            "L2": {
                                "status": "pass",
                                "summary": "来源归一化及历史回填中；自动测试已通过",
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


if __name__ == "__main__":
    unittest.main()

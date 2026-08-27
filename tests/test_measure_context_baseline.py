from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "measure_context_baseline.py"


def load_script():
    spec = importlib.util.spec_from_file_location("pm_context_baseline", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ContextBaselineCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = load_script()

    def test_baseline_counts_surfaces_without_token_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            task_dir = project / "docs" / "tasks" / "SPEC-001"
            prompt_dir = task_dir / "prompts"
            prompt_dir.mkdir(parents=True)
            task = {
                "schema_version": "3",
                "id": "SPEC-001",
                "title": "测试任务",
                "type": "spec",
                "priority": "P1",
                "status": "NEW",
                "lifecycle": {"next_action": "开始"},
                "verification": {"evidence_file": "evidence.json"},
                "blockers": [],
            }
            (task_dir / "task.json").write_text(
                json.dumps(task, ensure_ascii=False), encoding="utf-8"
            )
            (task_dir / "evidence.json").write_text(
                json.dumps({"verification": {"levels": {}}}), encoding="utf-8"
            )
            (prompt_dir / "01.md").write_text("聚焦实现", encoding="utf-8")
            board = project / "docs" / "dispatch-board.md"
            board.write_text("# 看板\n", encoding="utf-8")

            report = self.script.collect_context_baseline(
                project / "docs" / "tasks",
                board_path=board,
                generated_at="2026-08-27T00:00:00Z",
            )
            self.assertEqual(report["task_count"], 1)
            self.assertEqual(report["evidence_file_count"], 1)
            self.assertEqual(report["prompt_file_count"], 1)
            self.assertEqual(report["task_schema_versions"], {"3": 1})
            self.assertLessEqual(report["panels"]["actionable"]["chars"], 4000)
            self.assertIn("未使用模型相关 Token 估算", report["note"])


if __name__ == "__main__":
    unittest.main()

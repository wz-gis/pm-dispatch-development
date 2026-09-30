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

    def test_public_export_excludes_templates_aliases_and_duplicate_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tasks = Path(directory) / "docs" / "tasks"
            document = {
                "id": "SPEC-001", "title": "PRIVATE_TITLE", "type": "spec",
                "status": "NEW", "priority": "P1", "lifecycle": {},
            }
            for folder in ("SPEC-001", "legacy-alias", "TASK_TEMPLATE"):
                destination = tasks / folder
                destination.mkdir(parents=True)
                (destination / "task.yaml").write_text(json.dumps(document))
            (tasks / "SPEC-001" / "task.json").write_text(json.dumps(document))
            report = self.script.collect_context_baseline(
                tasks, canonical_only=True, generated_at="2026-09-04T00:00:00Z"
            )
            public = self.script.public_context_baseline(report)
            self.assertEqual(public["task_count"], 1)
            self.assertEqual(public["excluded_task_documents"], 3)
            self.assertEqual(public["task_types"]["spec"], 1)
            self.assertIsNone(public["board_chars"])
            for rendered in (json.dumps(public), self.script.render_public_markdown(public)):
                for private in (directory, "PRIVATE_TITLE", "SPEC-001", "legacy-alias"):
                    self.assertNotIn(private, rendered)

    def test_public_export_whitelists_labels_and_recomputes_ratios(self) -> None:
        report = {
            "generated_at": "2026-09-04T00:00:00Z",
            "task_count": 3, "excluded_task_documents": 0,
            "task_types": {"bug": 2, "PRIVATE_ORGANIZATION": 1},
            "evidence_file_count": 2, "prompt_file_count": 4,
            "totals": {"chars": 3000},
            "board": {"chars": 1000, "path": "/private/source"},
            "panels": {"all": {"chars": 500}, "actionable": {"chars": 100}},
            "unexpected_secret": "DO_NOT_EXPORT",
        }
        public = self.script.public_context_baseline(report)
        self.assertEqual(public["task_types"]["unknown"], 1)
        self.assertEqual(public["actionable_vs_all_reduction_pct"], 80.0)
        self.assertEqual(public["actionable_vs_board_reduction_pct"], 90.0)
        self.assertNotIn("PRIVATE_ORGANIZATION", json.dumps(public))
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(public))
        self.assertNotIn("/private/source", json.dumps(public))

    def test_public_export_counts_legacy_task_id_without_migrating_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tasks = Path(directory) / "docs" / "tasks"
            destination = tasks / "BUG-002"
            destination.mkdir(parents=True)
            path = destination / "task.yaml"
            original = json.dumps({"taskId": "BUG-002", "title": "Legacy bug", "status": "NEW"})
            path.write_text(original)
            report = self.script.collect_context_baseline(tasks, canonical_only=True)
            public = self.script.public_context_baseline(report)
            self.assertEqual(public["task_count"], 1)
            self.assertEqual(public["task_types"]["bug"], 1)
            self.assertEqual(path.read_text(), original)


if __name__ == "__main__":
    unittest.main()

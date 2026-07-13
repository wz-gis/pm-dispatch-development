from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractCase(unittest.TestCase):
    def test_task_panel_uses_fixed_decision_columns(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |", skill)

    def test_task_panel_keeps_runtime_metadata_out_of_main_view(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        panel = skill.split("## Task Panel", 1)[1].split("## Choose Strategy", 1)[0]
        self.assertIn("主面板不展示 Owner、Worker、Run、Lease、模型或 Adapter", panel)
        self.assertIn("<id> <title>", panel)


if __name__ == "__main__":
    unittest.main()

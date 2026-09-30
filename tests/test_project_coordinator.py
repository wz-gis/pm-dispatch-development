from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_pm_dispatch import LoadedTask, validate_project_coordinators


def task(project: str, task_id: str, owner: str, status: str = "active") -> LoadedTask:
    return LoadedTask(
        Path(project) / "docs/tasks" / task_id / "task.yaml",
        {"dispatch": {"heartbeat": {"coordinator_thread_id": owner, "status": status}}},
        None,
    )


class ProjectCoordinatorCase(unittest.TestCase):
    def test_multiple_tasks_share_one_pm(self) -> None:
        self.assertEqual(validate_project_coordinators([
            task("/project-a", "BUG-001", "pm-1"),
            task("/project-a", "BUG-002", "codex-thread:pm-1"),
        ]), [])

    def test_two_active_pms_in_one_project_fail(self) -> None:
        errors = validate_project_coordinators([
            task("/project-a", "BUG-001", "pm-1"),
            task("/project-a", "BUG-002", "pm-2"),
        ])
        self.assertEqual(len(errors), 1)
        self.assertIn("multiple active project Coordinators", errors[0])

    def test_projects_and_paused_history_are_independent(self) -> None:
        self.assertEqual(validate_project_coordinators([
            task("/project-a", "BUG-001", "pm-1"),
            task("/project-b", "BUG-001", "pm-2"),
            task("/project-a", "BUG-002", "old-pm", "paused"),
        ]), [])

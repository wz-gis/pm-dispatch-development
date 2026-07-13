from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATOR_PATH = ROOT / "scripts" / "migrate_pm_dispatch.py"
NOW = "2026-07-13T12:00:00Z"


def load_migrator():
    spec = importlib.util.spec_from_file_location("pm_migrator", MIGRATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def adapters() -> dict:
    result = {}
    for path in (ROOT / "references" / "adapters").glob("*.adapter.json"):
        adapter = json.loads(path.read_text(encoding="utf-8"))
        result[adapter["provider"]] = adapter
    return result


def legacy_worker_task() -> dict:
    return {
        "id": "bug001-env-block",
        "display_name": "bug001-env-block",
        "title": "环境阻塞",
        "type": "bug",
        "priority": "P1",
        "area": ["AA"],
        "dispatch": {
            "strategy": "single-worker",
            "provider": "codex",
            "reason": "legacy worker",
            "worker_required": True,
            "heartbeat_required": True,
            "selected_at": NOW,
            "max_parallel_workers": 1,
            "model_policy": {
                "difficulty": "hard",
                "tier": "reasoning",
                "selected_model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "reason": "legacy hard task",
                "override_allowed": False,
            },
            "batch": None,
            "heartbeat": None,
            "escalation_triggers": [],
        },
        "runs": [
            {
                "run_id": "run-bug001-env-block-impl-w01",
                "gate": "implementation",
                "worker_type": "codex-thread",
                "worker_name": "bug001-env-block-impl-w01",
                "worker_label": "bug001-env-block [impl w01]",
                "worker_id": "codex-thread:legacy",
                "model_tier": "reasoning",
                "selected_model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "model_reason": "legacy hard task",
                "status": "running",
                "allow_parallel": False,
                "started_at": NOW,
                "finished_at": None,
                "attempts": [
                    {
                        "attempt_id": "attempt-bug001-env-block-impl-w01-a01",
                        "status": "running",
                        "lease": {"holder": "run-bug001-env-block-impl-w01"},
                    }
                ],
            }
        ],
    }


class MigratorCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.migrator = load_migrator()
        cls.adapters = adapters()

    def test_migrates_legacy_id_and_display_name(self) -> None:
        migrated = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        self.assertEqual(migrated["schema_version"], "2")
        self.assertEqual(migrated["id"], "BUG-001")
        self.assertEqual(migrated["display_name"], "BUG-001 P1 AA 环境阻塞")

    def test_splits_legacy_model_policy_into_request_resolution_and_run_actuals(self) -> None:
        migrated = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        dispatch = migrated["dispatch"]
        self.assertNotIn("model_policy", dispatch)
        self.assertEqual(dispatch["model_request"]["reasoning_profile"], "deep")
        self.assertEqual(dispatch["resolution"]["provider_reasoning_effort"], "high")
        run = migrated["runs"][0]
        self.assertNotIn("selected_model", run)
        self.assertEqual(run["model_id"], "gpt-5.6-sol")
        self.assertEqual(run["reasoning_profile"], "deep")
        self.assertEqual(run["worker_name"], "BUG-001-impl-w01")
        self.assertEqual(run["run_id"], "run-BUG-001-impl-w01")
        self.assertEqual(
            run["attempts"][0]["attempt_id"], "attempt-BUG-001-impl-w01-a01"
        )
        self.assertEqual(run["attempts"][0]["lease"]["holder"], run["run_id"])

    def test_legacy_string_evidence_becomes_non_passing_structured_artifact(self) -> None:
        evidence = {
            "task_id": "bug001-env-block",
            "generated_at": NOW,
            "artifacts": {"browser": ["looked good"], "commands": ["python3 -m unittest"]},
        }
        migrated = self.migrator.migrate_evidence(evidence, NOW)
        self.assertEqual(migrated["schema_version"], "2")
        self.assertEqual(migrated["task_id"], "BUG-001")
        self.assertEqual(migrated["artifacts"]["browser"][0]["result"], "info")
        self.assertEqual(migrated["artifacts"]["commands"][0]["result"], "info")
        self.assertEqual(migrated["artifacts"]["commands"][0]["exit_code"], -1)

    def test_v2_migration_is_idempotent(self) -> None:
        once = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        twice = self.migrator.migrate_task(copy.deepcopy(once), self.adapters, NOW)
        self.assertEqual(twice, once)


if __name__ == "__main__":
    unittest.main()

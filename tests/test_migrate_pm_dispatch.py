from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
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
MIGRATOR_PATH = ROOT / "scripts" / "migrate_pm_dispatch.py"
EVIDENCE_SCHEMA_PATH = ROOT / "references" / "schemas" / "evidence.schema.json"
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
    heartbeat = copy.deepcopy(codex_dispatch()["heartbeat"])
    heartbeat.pop("target_run_id")
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
                "selected_model": "legacy-explicit-model",
                "reasoning_effort": "high",
                "reason": "legacy hard task",
                "override_allowed": False,
            },
            "batch": None,
            "heartbeat": heartbeat,
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
                "selected_model": "legacy-explicit-model",
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
        self.assertEqual(migrated["schema_version"], "3")
        self.assertEqual(migrated["id"], "BUG-001")
        self.assertEqual(migrated["display_name"], "BUG-001 P1 AA 环境阻塞")
        self.assertEqual(
            migrated["quality_checks"], {"policy": "risk-scaled", "checks": []}
        )

    def test_converts_legacy_model_selection_to_inherited_codex_model(self) -> None:
        migrated = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        dispatch = migrated["dispatch"]
        self.assertNotIn("model_policy", dispatch)
        self.assertNotIn("model_request", dispatch)
        self.assertEqual(dispatch["reasoning_profile"], "deep")
        self.assertIsNone(dispatch["resolution"]["model_id"])
        self.assertEqual(dispatch["resolution"]["provider_reasoning_effort"], "high")
        run = migrated["runs"][0]
        self.assertNotIn("selected_model", run)
        self.assertIsNone(run["model_id"])
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
        self.assertEqual(migrated["quality_checks"], [])

    def test_current_evidence_backfills_empty_quality_contract(self) -> None:
        migrated = self.migrator.migrate_evidence({"schema_version": "2"}, NOW)
        self.assertEqual(migrated["quality_checks"], [])

    def test_v3_migration_is_idempotent(self) -> None:
        once = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        twice = self.migrator.migrate_task(copy.deepcopy(once), self.adapters, NOW)
        self.assertEqual(twice, once)

    def test_splits_embedded_runtime_from_task_contract(self) -> None:
        embedded = self.migrator.migrate_task(
            legacy_worker_task(), self.adapters, NOW
        )
        task, runtime = self.migrator.split_task_runtime(embedded, NOW)
        self.assertEqual(task["schema_version"], "4")
        self.assertEqual(task["runtime_file"], "runtime.yaml")
        self.assertNotIn("runs", task)
        self.assertNotIn("resources", task)
        self.assertNotIn("resolution", task["dispatch"])
        self.assertNotIn("heartbeat", task["dispatch"])
        self.assertEqual(runtime["schema_version"], "1")
        self.assertEqual(runtime["task_id"], "BUG-001")
        self.assertEqual(runtime["runs"][0]["continuation_token"], None)
        self.assertEqual(runtime["event_log_file"], "events.jsonl")

    def test_cli_writes_task_v4_runtime_and_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "BUG-041"
            task_dir.mkdir()
            path = task_dir / "task.yaml"
            path.write_text(json.dumps(base_task(), ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(MIGRATOR_PATH),
                    str(path),
                    "--now",
                    NOW,
                    "--write",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            task = json.loads(path.read_text(encoding="utf-8"))
            runtime = json.loads((task_dir / "runtime.yaml").read_text(encoding="utf-8"))
            self.assertEqual(task["schema_version"], "4")
            self.assertNotIn("runs", task)
            self.assertEqual(runtime["task_id"], "BUG-041")
            self.assertTrue((task_dir / "events.jsonl").exists())
            self.assertTrue(path.with_suffix(".yaml.v3.bak").exists())

    def test_existing_v3_task_backfills_inherited_model(self) -> None:
        task = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        task["dispatch"]["resolution"].pop("model_id")
        task["runs"][0].pop("model_id")
        normalized = self.migrator.migrate_task(task, self.adapters, NOW)
        self.assertIsNone(normalized["dispatch"]["resolution"]["model_id"])
        self.assertIsNone(normalized["runs"][0]["model_id"])
        self.assertEqual(normalized["dispatch"]["resolution"]["adapter_version"], "15")
        self.assertEqual(normalized["runs"][0]["adapter_version"], "15")
        self.assertEqual(normalized["runs"][0]["wait_budget"]["max_calls"], 1)
        self.assertEqual(normalized["runs"][0]["wait_budget"]["max_timeout_ms"], 30000)
        self.assertEqual(
            normalized["runs"][0]["inspection_budget"]["min_interval_seconds"],
            600,
        )

    def test_active_v4_codex_run_upgrades_to_v15_control_budgets(self) -> None:
        task = base_task("SPEC-101")
        task.update(
            {
                "display_name": "SPEC-101 P1 AA Add page",
                "title": "Add page",
                "type": "spec",
                "status": "IN_IMPL",
            }
        )
        task["lifecycle"]["phase"] = "implementation"
        task["dispatch"] = codex_dispatch()
        task["runs"] = [codex_run()]
        task, runtime = split_runtime(task)
        runtime["resolution"]["adapter_version"] = "11"
        runtime["runs"][0]["adapter_version"] = "11"
        runtime["runs"][0].pop("wait_budget")

        normalized = self.migrator.normalize_runtime_routes(
            task, runtime, self.adapters, NOW
        )

        self.assertEqual(normalized["resolution"]["adapter_version"], "15")
        self.assertEqual(normalized["runs"][0]["adapter_version"], "15")
        self.assertEqual(
            normalized["runs"][0]["wait_budget"],
            {
                "policy": "single-short",
                "max_calls": 1,
                "max_timeout_ms": 30000,
                "enforced_at": NOW,
            },
        )
        self.assertEqual(
            normalized["runs"][0]["inspection_budget"],
            {
                "policy": "incremental-debounce",
                "min_interval_seconds": 600,
                "max_calls_per_cycle": 1,
                "enforced_at": NOW,
            },
        )

    def test_terminal_v4_run_preserves_v11_history(self) -> None:
        task = base_task("SPEC-101")
        task.update(
            {
                "display_name": "SPEC-101 P1 AA Add page",
                "title": "Add page",
                "type": "spec",
                "status": "VERIFIED",
            }
        )
        task["lifecycle"]["phase"] = "closure"
        task["closure"]["status"] = "ready"
        task["verification"]["status"] = "L1_VERIFIED"
        task["dispatch"] = codex_dispatch()
        run = codex_run()
        run.update({"adapter_version": "11", "status": "succeeded", "finished_at": NOW})
        run.pop("wait_budget")
        run["attempts"][0].update({"status": "succeeded", "finished_at": NOW})
        task["runs"] = [run]
        task, runtime = split_runtime(task)
        runtime["resolution"]["adapter_version"] = "11"

        normalized = self.migrator.normalize_runtime_routes(
            task, runtime, self.adapters, NOW
        )

        self.assertEqual(normalized["resolution"]["adapter_version"], "11")
        self.assertEqual(normalized["runs"][0]["adapter_version"], "11")
        self.assertNotIn("wait_budget", normalized["runs"][0])
        errors: list[str] = []
        self.migrator.validate_adapter_resolution(
            self.migrator.compose_task_runtime(task, normalized),
            self.adapters,
            errors,
            "terminal-runtime",
        )
        self.assertEqual(errors, [])

    def test_worker_migration_requires_heartbeat_and_backfills_autonomy(self) -> None:
        migrated = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        dispatch = migrated["dispatch"]
        self.assertEqual(dispatch["resolution"]["monitor_mode"], "heartbeat")
        self.assertIn("heartbeat", dispatch["resolution"]["capabilities"])
        self.assertEqual(dispatch["heartbeat"]["status"], "active")
        self.assertEqual(dispatch["autonomy_policy"]["default_action"], "proceed")
        self.assertEqual(
            dispatch["design_freeze"]["change_policy"],
            "material-only-new-attempt",
        )
        lease = migrated["runs"][0]["attempts"][0]["lease"]
        self.assertEqual(lease["progress_seq"], 0)
        self.assertEqual(lease["last_progress_at"], NOW)
        self.assertEqual(lease["last_progress_summary"], "migrated lease; progress unknown")
        self.assertIsNone(lease["event_cursor"])
        self.assertEqual(lease["liveness_state"], "live")
        self.assertIsNone(lease["monitor_gap_started_at"])
        self.assertEqual(lease["disconnect_probe_count"], 0)
        self.assertIsNone(lease["disconnect_first_seen_at"])
        self.assertEqual(dispatch["worker_reuse"]["mode"], "sticky")
        self.assertTrue(dispatch["worker_reuse"]["reuse_across_gates"])

    def test_existing_heartbeat_is_moved_to_ten_minute_incremental_scan(self) -> None:
        task = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        task["dispatch"]["heartbeat"] = {
            "automation_id": "automation-001",
            "coordinator_thread_id": "codex-thread:pm-1",
            "monitor_thread_id": "codex-thread:legacy-monitor",
            "interval_minutes": 15,
            "max_checks": 4,
            "stop_condition": "run terminal",
            "lightweight": True,
            "status": "active",
        }
        normalized = self.migrator.migrate_task(task, self.adapters, NOW)
        heartbeat = normalized["dispatch"]["heartbeat"]
        self.assertEqual(normalized["dispatch"]["resolution"]["monitor_mode"], "heartbeat")
        self.assertEqual(heartbeat["scan_scope"], "incremental")
        self.assertEqual(
            heartbeat["read_set"],
            ["worker-status", "lease", "latest-milestone"],
        )
        self.assertEqual(heartbeat["context_policy"], "coordinator")
        self.assertEqual(heartbeat["interval_minutes"], 10)
        self.assertNotIn("monitor_thread_id", heartbeat)
        self.assertTrue(heartbeat["lightweight"])
        self.assertEqual(heartbeat["coordinator_epoch"], 1)

    def test_workerless_queued_runtime_becomes_bounded_provisioning(self) -> None:
        task = base_task("SPEC-101")
        task.update({"status": "IN_IMPL", "type": "spec"})
        task["lifecycle"]["phase"] = "implementation"
        task["dispatch"] = codex_dispatch()
        run = codex_run()
        run["status"] = "queued"
        run["worker_id"] = None
        run["attempts"][0]["status"] = "queued"
        run["attempts"][0]["lease"] = None
        task["runs"] = [run]
        task, runtime = split_runtime(task)

        normalized = self.migrator.normalize_runtime_routes(
            task, runtime, self.adapters, NOW
        )

        migrated = normalized["runs"][0]
        self.assertEqual(migrated["status"], "provisioning")
        self.assertEqual(migrated["attempts"][0]["status"], "provisioning")
        self.assertEqual(migrated["provisioning"]["status"], "pending")
        self.assertEqual(
            migrated["provisioning"]["deadline_at"], "2026-07-13T12:02:00Z"
        )

    def test_stopped_legacy_heartbeat_backfills_historical_coordinator(self) -> None:
        task = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        task["runs"][0].update({"status": "succeeded", "finished_at": NOW})
        task["runs"][0]["attempts"][0].update(
            {"status": "succeeded", "finished_at": NOW}
        )
        task["dispatch"]["heartbeat"] = {
            "automation_id": "legacy-heartbeat",
            "interval_minutes": 15,
            "max_checks": 4,
            "stop_condition": "legacy run reached terminal state",
            "lightweight": True,
            "status": "stopped",
        }

        normalized = self.migrator.migrate_task(task, self.adapters, NOW)

        self.assertEqual(
            normalized["dispatch"]["heartbeat"]["coordinator_thread_id"],
            "legacy-coordinator:BUG-001",
        )

    def test_active_codex_migration_rejects_paused_heartbeat(self) -> None:
        task = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        task["dispatch"]["heartbeat"] = {
            "automation_id": "legacy-heartbeat",
            "interval_minutes": 15,
            "max_checks": 4,
            "stop_condition": "legacy run reached terminal state",
            "lightweight": True,
            "status": "paused",
        }

        with self.assertRaisesRegex(
            self.migrator.MigrationError, "active coordinator Heartbeat"
        ):
            self.migrator.migrate_task(task, self.adapters, NOW)

    def test_existing_v3_external_task_drops_undeclared_model(self) -> None:
        task = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        task["dispatch"]["resolution"]["provider"] = "external-cli"
        task["dispatch"]["resolution"]["model_id"] = "stale-model"
        task["runs"][0]["provider"] = "external-cli"
        task["runs"][0]["model_id"] = "stale-model"
        normalized = self.migrator.migrate_task(task, self.adapters, NOW)
        self.assertIsNone(normalized["dispatch"]["resolution"]["model_id"])
        self.assertIsNone(normalized["runs"][0]["model_id"])

    def test_v2_task_drops_codex_model_override(self) -> None:
        v2 = self.migrator.migrate_task(legacy_worker_task(), self.adapters, NOW)
        v2["schema_version"] = "2"
        v2["dispatch"]["model_request"] = {
            "quality": "frontier",
            "reasoning_profile": v2["dispatch"].pop("reasoning_profile"),
            "latency": "normal",
            "cost": "balanced",
        }
        v2["dispatch"]["fallback_policy"]["allow_model_substitution"] = False
        v2["dispatch"]["resolution"]["model_id"] = "legacy-explicit-model"
        v2["runs"][0]["model_id"] = "legacy-explicit-model"

        migrated = self.migrator.migrate_task(v2, self.adapters, NOW)
        self.assertEqual(migrated["schema_version"], "3")
        self.assertNotIn("model_request", migrated["dispatch"])
        self.assertNotIn("allow_model_substitution", migrated["dispatch"]["fallback_policy"])
        self.assertIsNone(migrated["dispatch"]["resolution"]["model_id"])
        self.assertIsNone(migrated["runs"][0]["model_id"])

    def test_partial_dict_artifact_is_normalized_to_v2_schema(self) -> None:
        evidence = {
            "task_id": "bug001-env-block",
            "generated_at": NOW,
            "artifacts": {"browser": [{"kind": "browser", "subject": "partial"}]},
        }
        migrated = self.migrator.migrate_evidence(evidence, NOW)
        browser = migrated["artifacts"]["browser"][0]
        self.assertEqual(browser["result"], "info")
        schema = json.loads(EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = self.migrator.validate_schema(migrated, schema, "evidence", schema)
        self.assertEqual(errors, [])

    def test_unknown_worker_provider_fails_instead_of_guessing_adapter(self) -> None:
        task = legacy_worker_task()
        task["dispatch"]["provider"] = "missing-provider"
        with self.assertRaisesRegex(self.migrator.MigrationError, "missing-provider"):
            self.migrator.migrate_task(task, self.adapters, NOW)

    def test_write_validates_first_and_creates_backup_atomically(self) -> None:
        evidence = {
            "task_id": "bug001-env-block",
            "generated_at": NOW,
            "artifacts": {"browser": ["legacy browser claim"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.yaml"
            original = json.dumps(evidence, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(MIGRATOR_PATH),
                    str(path),
                    "--now",
                    NOW,
                    "--write",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            backup = path.with_suffix(".yaml.v1.bak")
            self.assertEqual(backup.read_text(encoding="utf-8"), original)
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], "2")

    def test_invalid_migration_does_not_overwrite_source(self) -> None:
        task = legacy_worker_task()
        task.pop("title")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task.yaml"
            original = json.dumps(task, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(MIGRATOR_PATH),
                    str(path),
                    "--now",
                    NOW,
                    "--write",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertFalse(path.with_suffix(".yaml.v1.bak").exists())


if __name__ == "__main__":
    unittest.main()

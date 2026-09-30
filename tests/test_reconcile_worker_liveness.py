from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .test_validate_pm_dispatch import codex_run
except ImportError:
    from test_validate_pm_dispatch import codex_run


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_worker_liveness.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pm_liveness", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LivenessCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def task(self) -> dict:
        run = codex_run()
        return {
            "runs": [run],
            "resources": {
                "locks": [
                    {
                        "resource_id": "repo:test",
                        "holder_run_id": run["run_id"],
                        "status": "active",
                        "lease_expires_at": "2026-07-13T13:00:00Z",
                    }
                ]
            },
            "last_updated": "2026-07-13T12:00:00Z",
        }

    def test_live_probe_renews_same_attempt_and_preserves_progress(self) -> None:
        source = self.task()
        source["runs"][0]["attempts"][0]["lease"]["last_progress_at"] = "2026-07-13T12:50:00Z"
        result, outcome = self.module.reconcile_liveness(
            source,
            source["runs"][0]["run_id"],
            "running",
            datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc),
        )
        lease = result["runs"][0]["attempts"][0]["lease"]
        self.assertEqual(outcome, "renewed-same-attempt")
        self.assertEqual(result["runs"][0]["attempts"][0]["attempt_id"], source["runs"][0]["attempts"][0]["attempt_id"])
        self.assertEqual(lease["last_progress_summary"], "worker dispatched")
        self.assertEqual(lease["renew_count"], 1)
        self.assertEqual(lease["liveness_state"], "live")
        self.assertIsNone(lease["monitor_gap_started_at"])
        self.assertEqual(
            result["resources"]["locks"][0]["lease_expires_at"],
            lease["expires_at"],
        )

    def test_first_unreachable_probe_opens_grace_without_new_attempt(self) -> None:
        source = self.task()
        result, outcome = self.module.reconcile_liveness(
            source,
            source["runs"][0]["run_id"],
            "unreachable",
            datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc),
        )
        run = result["runs"][0]
        self.assertEqual(outcome, "grace-probe-required")
        self.assertEqual(run["status"], "running")
        self.assertEqual(len(run["attempts"]), 1)
        self.assertEqual(run["attempts"][0]["lease"]["disconnect_probe_count"], 1)
        self.assertEqual(run["attempts"][0]["lease"]["liveness_state"], "unknown")
        self.assertEqual(
            result["resources"]["locks"][0]["lease_expires_at"],
            run["attempts"][0]["lease"]["expires_at"],
        )

    def test_monitor_outage_holds_attempt_and_lock_without_shortening_lease(self) -> None:
        source = self.task()
        original_expiry = source["runs"][0]["attempts"][0]["lease"]["expires_at"]
        result, outcome = self.module.reconcile_liveness(
            source,
            source["runs"][0]["run_id"],
            "monitor-unavailable",
            datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc),
        )
        run = result["runs"][0]
        lease = run["attempts"][0]["lease"]
        self.assertEqual(outcome, "ownership-held-monitor-gap")
        self.assertEqual(run["status"], "running")
        self.assertEqual(len(run["attempts"]), 1)
        self.assertEqual(lease["expires_at"], original_expiry)
        self.assertEqual(lease["liveness_state"], "unknown")
        self.assertEqual(lease["monitor_gap_started_at"], "2026-07-13T13:00:00Z")
        self.assertEqual(result["resources"]["locks"][0]["status"], "active")

    def test_second_unreachable_probe_expires_attempt_and_releases_lock(self) -> None:
        source = self.task()
        lease = source["runs"][0]["attempts"][0]["lease"]
        lease["disconnect_probe_count"] = 1
        lease["disconnect_first_seen_at"] = "2026-07-13T13:00:00Z"
        result, outcome = self.module.reconcile_liveness(
            source,
            source["runs"][0]["run_id"],
            "unreachable",
            datetime(2026, 7, 13, 13, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(outcome, "expired-replacement-allowed")
        self.assertEqual(result["runs"][0]["status"], "expired")
        self.assertEqual(result["runs"][0]["attempts"][0]["status"], "expired")
        self.assertEqual(result["resources"]["locks"][0]["status"], "released")

    def test_probe_does_not_mutate_source(self) -> None:
        source = self.task()
        original = copy.deepcopy(source)
        self.module.reconcile_liveness(
            source,
            source["runs"][0]["run_id"],
            "running",
            datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(source, original)

    def test_idle_interrupted_keeps_identity_and_ownership_without_claiming_success(self) -> None:
        source = self.task()
        run_id = source["runs"][0]["run_id"]
        now = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
        result, outcome = self.module.reconcile_liveness(
            source, run_id, "idle", now, latest_turn_status="interrupted"
        )
        run = result["runs"][0]
        self.assertEqual(outcome, "diagnosis-required")
        self.assertEqual(run["observation"]["reason"], "interrupted")
        self.assertEqual(run["status"], "queued")
        self.assertEqual(run["worker_id"], source["runs"][0]["worker_id"])
        self.assertEqual(run["attempts"][0]["attempt_id"], source["runs"][0]["attempts"][0]["attempt_id"])
        self.assertEqual(result["resources"]["locks"][0]["status"], "active")
        self.assertIsNone(run["finished_at"])
        repeated, outcome = self.module.reconcile_liveness(result, run_id, "idle", now + timedelta(minutes=10))
        self.assertEqual(outcome, "awaiting-diagnosis")
        self.assertEqual(repeated["runs"][0]["observation"]["attention_at"], run["observation"]["attention_at"])

    def test_stale_running_worker_requests_one_diagnosis_until_real_progress(self) -> None:
        source = self.task()
        run_id = source["runs"][0]["run_id"]
        now = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
        first, outcome = self.module.reconcile_liveness(source, run_id, "running", now)
        self.assertEqual(outcome, "diagnosis-required")
        self.assertEqual(first["runs"][0]["observation"]["reason"], "no-progress")
        second, outcome = self.module.reconcile_liveness(first, run_id, "running", now + timedelta(minutes=10))
        self.assertEqual(outcome, "awaiting-diagnosis")
        lease = second["runs"][0]["attempts"][0]["lease"]
        lease["progress_seq"] += 1
        lease["last_progress_at"] = "2026-07-13T13:15:00Z"
        third, outcome = self.module.reconcile_liveness(second, run_id, "running", now + timedelta(minutes=20))
        self.assertEqual(outcome, "renewed-same-attempt")
        self.assertEqual(third["runs"][0]["observation"]["state"], "active")

    def test_verified_long_command_has_fixed_deadline_not_infinite_renewal(self) -> None:
        source = self.task()
        run_id = source["runs"][0]["run_id"]
        now = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
        first, outcome = self.module.reconcile_liveness(
            source, run_id, "running", now,
            command_id="build-session-1", command_deadline="2026-07-13T13:25:00Z"
        )
        self.assertEqual(outcome, "renewed-same-attempt")
        self.assertEqual(first["runs"][0]["observation"]["state"], "waiting-command")
        second, outcome = self.module.reconcile_liveness(first, run_id, "running", now + timedelta(minutes=10))
        self.assertEqual(outcome, "renewed-same-attempt")
        with self.assertRaisesRegex(ValueError, "cannot be extended"):
            self.module.reconcile_liveness(
                second, run_id, "running", now + timedelta(minutes=20),
                command_id="build-session-1", command_deadline="2026-07-13T14:00:00Z"
            )
        _, outcome = self.module.reconcile_liveness(second, run_id, "running", now + timedelta(minutes=30))
        self.assertEqual(outcome, "diagnosis-required")

    def test_confirmed_terminal_reconciliation_is_idempotent(self) -> None:
        source = self.task()
        run_id = source["runs"][0]["run_id"]
        now = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
        first, outcome = self.module.reconcile_liveness(source, run_id, "succeeded", now)
        self.assertEqual(outcome, "terminal-succeeded")
        second, outcome = self.module.reconcile_liveness(first, run_id, "idle", now + timedelta(minutes=10))
        self.assertEqual(outcome, "terminal-already-reconciled")
        self.assertEqual(first, second)
        self.assertEqual(second["resources"]["locks"][0]["status"], "released")

    def test_idle_completed_turn_requires_explicit_terminal_outcome(self) -> None:
        source = self.task()
        run_id = source["runs"][0]["run_id"]
        now = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "explicit terminal outcome"):
            self.module.reconcile_liveness(
                source, run_id, "idle", now, latest_turn_status="completed"
            )
        result, outcome = self.module.reconcile_liveness(
            source,
            run_id,
            "idle",
            now,
            latest_turn_status="completed",
            terminal_outcome="succeeded",
        )
        self.assertEqual(outcome, "terminal-succeeded")
        self.assertEqual(result["runs"][0]["status"], "succeeded")

    def test_one_diagnosis_can_identify_a_legitimate_running_command(self) -> None:
        source = self.task()
        run_id = source["runs"][0]["run_id"]
        now = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
        first, outcome = self.module.reconcile_liveness(source, run_id, "running", now)
        self.assertEqual(outcome, "diagnosis-required")
        second, outcome = self.module.reconcile_liveness(
            first, run_id, "running", now + timedelta(minutes=1),
            command_id="build-1", command_deadline="2026-07-13T13:25:00Z"
        )
        self.assertEqual(outcome, "renewed-same-attempt")
        self.assertEqual(second["runs"][0]["observation"]["state"], "waiting-command")
        _, outcome = self.module.reconcile_liveness(second, run_id, "running", now + timedelta(minutes=30))
        self.assertEqual(outcome, "diagnosis-required")

    def test_observation_schema_and_context_digest_ignore_status_only_time(self) -> None:
        from context_source_digest import runtime_context_projection
        from validate_pm_dispatch import validate_schema

        source = self.task()
        run_id = source["runs"][0]["run_id"]
        now = datetime(2026, 7, 13, 12, 10, tzinfo=timezone.utc)
        first, _ = self.module.reconcile_liveness(source, run_id, "running", now)
        second, _ = self.module.reconcile_liveness(first, run_id, "running", now + timedelta(minutes=10))
        schema = json.loads((ROOT / "references/schemas/runtime.schema.json").read_text())
        errors = validate_schema(first["runs"][0]["observation"], schema["$defs"]["observation"], "observation", schema)
        self.assertEqual(errors, [])
        self.assertEqual(runtime_context_projection(first), runtime_context_projection(second))

    def test_cli_resolves_task_v4_runtime_sidecar(self) -> None:
        runtime = self.task()
        task = {
            "schema_version": "4",
            "id": "SPEC-101",
            "runtime_file": "runtime.yaml",
            "dispatch": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = root / "task.yaml"
            runtime_path = root / "runtime.yaml"
            task_path.write_text(json.dumps(task), encoding="utf-8")
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    str(task_path),
                    "--run-id",
                    runtime["runs"][0]["run_id"],
                    "--probe-status",
                    "running",
                    "--now",
                    "2026-07-13T13:00:00Z",
                    "--write",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            updated = json.loads(runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["runs"][0]["attempts"][0]["lease"]["renew_count"], 1
            )
            self.assertEqual(json.loads(task_path.read_text(encoding="utf-8")), task)


if __name__ == "__main__":
    unittest.main()

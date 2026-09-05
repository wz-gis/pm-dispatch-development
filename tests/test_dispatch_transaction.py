from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import timedelta
from pathlib import Path

from tests.test_validate_pm_dispatch import (
    base_task,
    codex_dispatch,
    codex_run,
    split_runtime,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "manage_dispatch_transaction.py"
NOW = "2026-07-13T12:00:00Z"


def load_script():
    spec = importlib.util.spec_from_file_location("pm_dispatch_transaction", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def provisioning_bundle() -> dict:
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
    _, runtime = split_runtime(task)
    return runtime


class DispatchTransactionCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = load_script()

    def test_begin_and_complete_bind_worker_and_lease(self) -> None:
        runtime = provisioning_bundle()
        run = runtime["runs"][0]
        now = self.script.parse_time(NOW)
        attempt, change = self.script.begin(
            runtime,
            run,
            transaction_id="create-SPEC-101-a01",
            now=now,
            ttl_seconds=120,
        )
        self.assertEqual(change, "changed")
        self.assertEqual(run["status"], "provisioning")
        self.assertEqual(attempt["status"], "provisioning")
        self.assertIsNone(attempt["lease"])

        attempt, change = self.script.complete(
            runtime,
            run,
            transaction_id="create-SPEC-101-a01",
            worker_id="codex-thread:worker-101",
            now=now + timedelta(seconds=30),
            lease_seconds=3600,
        )
        self.assertEqual(change, "changed")
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["provisioning"]["status"], "completed")
        self.assertEqual(attempt["lease"]["holder"], run["run_id"])

    def test_rollback_requires_stopped_heartbeat_assertion(self) -> None:
        runtime = provisioning_bundle()
        run = runtime["runs"][0]
        now = self.script.parse_time(NOW)
        self.script.begin(
            runtime,
            run,
            transaction_id="create-SPEC-101-a01",
            now=now,
            ttl_seconds=120,
        )
        with self.assertRaisesRegex(ValueError, "pause or stop"):
            self.script.rollback(
                runtime,
                run,
                transaction_id="create-SPEC-101-a01",
                failure="create failed",
                now=now + timedelta(seconds=121),
                heartbeat_stopped=False,
            )
        attempt, _ = self.script.rollback(
            runtime,
            run,
            transaction_id="create-SPEC-101-a01",
            failure="create failed",
            now=now + timedelta(seconds=121),
            heartbeat_stopped=True,
        )
        self.assertEqual(run["status"], "cancelled")
        self.assertEqual(attempt["status"], "cancelled")
        self.assertEqual(runtime["heartbeat"]["status"], "stopped")

    def test_complete_rejects_exact_provisioning_deadline(self) -> None:
        runtime = provisioning_bundle()
        run = runtime["runs"][0]
        now = self.script.parse_time(NOW)
        self.script.begin(
            runtime,
            run,
            transaction_id="create-SPEC-101-a01",
            now=now,
            ttl_seconds=120,
        )
        with self.assertRaisesRegex(ValueError, "deadline expired"):
            self.script.complete(
                runtime,
                run,
                transaction_id="create-SPEC-101-a01",
                worker_id="codex-thread:worker-101",
                now=now + timedelta(seconds=120),
                lease_seconds=3600,
            )

    def test_complete_requires_heartbeat_to_remain_active(self) -> None:
        runtime = provisioning_bundle()
        run = runtime["runs"][0]
        now = self.script.parse_time(NOW)
        self.script.begin(
            runtime,
            run,
            transaction_id="create-SPEC-101-a01",
            now=now,
            ttl_seconds=120,
        )
        runtime["heartbeat"]["status"] = "stopped"
        with self.assertRaisesRegex(ValueError, "active coordinator Heartbeat"):
            self.script.complete(
                runtime,
                run,
                transaction_id="create-SPEC-101-a01",
                worker_id="codex-thread:worker-101",
                now=now + timedelta(seconds=30),
                lease_seconds=3600,
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import importlib.util
import json
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
PREFLIGHT_PATH = ROOT / "scripts" / "dispatch_preflight.py"


def load_preflight():
    spec = importlib.util.spec_from_file_location("pm_dispatch_preflight", PREFLIGHT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worker_bundle() -> tuple[dict, dict]:
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
    return split_runtime(task)


def provisioning_bundle() -> tuple[dict, dict]:
    task, runtime = worker_bundle()
    run = runtime["runs"][0]
    run["status"] = "provisioning"
    run["worker_id"] = None
    run["last_operation"] = "provision"
    run["attempts"][0]["status"] = "provisioning"
    run["attempts"][0]["lease"] = None
    run["provisioning"] = {
        "transaction_id": "create-SPEC-101-a01",
        "status": "pending",
        "started_at": "2026-07-13T12:00:00Z",
        "deadline_at": "2099-07-13T12:02:00Z",
        "finished_at": None,
        "failure": None,
    }
    return task, runtime


class DispatchPreflightCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preflight = load_preflight()

    def write_bundle(self, root: Path, task: dict, runtime: dict) -> Path:
        task_path = root / "task.yaml"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        (root / "runtime.yaml").write_text(json.dumps(runtime), encoding="utf-8")
        return task_path

    def test_worker_create_requires_heartbeat_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task, runtime = worker_bundle()
            runtime["heartbeat"] = None
            task_path = self.write_bundle(Path(directory), task, runtime)

            with self.assertRaisesRegex(ValueError, "active coordinator Heartbeat"):
                self.preflight.assert_heartbeat_dispatch_ready(task_path, task, None)

    def test_worker_create_rejects_paused_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task, runtime = worker_bundle()
            runtime["heartbeat"]["status"] = "paused"
            task_path = self.write_bundle(Path(directory), task, runtime)

            with self.assertRaisesRegex(ValueError, "active coordinator Heartbeat"):
                self.preflight.assert_heartbeat_dispatch_ready(task_path, task, None)

    def test_worker_create_accepts_active_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task, runtime = worker_bundle()
            task_path = self.write_bundle(Path(directory), task, runtime)

            heartbeat_id = self.preflight.assert_heartbeat_dispatch_ready(
                task_path, copy.deepcopy(task), None
            )

            self.assertEqual(heartbeat_id, "automation-001")

    def test_worker_create_accepts_bounded_provisioning_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task, runtime = provisioning_bundle()
            task_path = self.write_bundle(Path(directory), task, runtime)
            self.assertEqual(
                self.preflight.assert_heartbeat_dispatch_ready(task_path, task, None),
                "automation-001",
            )

    def test_worker_create_rejects_expired_provisioning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task, runtime = provisioning_bundle()
            runtime["runs"][0]["provisioning"]["deadline_at"] = "2020-01-01T00:00:00Z"
            task_path = self.write_bundle(Path(directory), task, runtime)
            with self.assertRaisesRegex(ValueError, "deadline expired"):
                self.preflight.assert_heartbeat_dispatch_ready(task_path, task, None)

    def test_new_worker_is_blocked_when_coordinator_budget_requires_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task, runtime = provisioning_bundle()
            task_path = self.write_bundle(root, task, runtime)
            session_dir = root / "sessions"
            session_dir.mkdir()
            token_record = json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 1_000_000,
                                "cached_input_tokens": 900_000,
                            },
                            "last_token_usage": {"input_tokens": 20_000},
                            "model_context_window": 258_400,
                        },
                    },
                }
            )
            (session_dir / "rollout-pm-1.jsonl").write_text(
                "\n".join([token_record] * 150), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "new epoch"):
                self.preflight.run_preflight(
                    task_path,
                    project_root=root,
                    output_dir=root / "context",
                    gate="implementation",
                    focus=[],
                    verification_commands=[],
                    max_chars=6000,
                    max_files=100,
                    generated_at="2026-07-13T12:00:00Z",
                    automation_dir=None,
                    coordinator_session_dir=session_dir,
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "authorize_terminal_wait.py"
NOW = "2026-09-01T06:00:00Z"
RUN_ID = "run-SPEC-042-impl-w01"


class TerminalWaitCase(unittest.TestCase):
    def make_bundle(self, root: Path, *, heartbeat_status: str = "active") -> None:
        task = {
            "schema_version": "4",
            "id": "SPEC-042",
            "runtime_file": "runtime.yaml",
            "dispatch": {},
        }
        runtime = {
            "schema_version": "1",
            "task_id": "SPEC-042",
            "task_schema_version": "4",
            "heartbeat": {
                "automation_id": "pm-spec-042",
                "coordinator_thread_id": "pm-thread-1",
                "target_run_id": RUN_ID,
                "status": heartbeat_status,
            },
            "runs": [
                {
                    "run_id": RUN_ID,
                    "provider": "codex",
                    "adapter_version": "12",
                    "worker_id": "thread-42",
                    "status": "running",
                    "event_cursor": "cursor-8",
                    "wait_budget": {
                        "policy": "single-short",
                        "max_calls": 1,
                        "max_timeout_ms": 30000,
                        "enforced_at": NOW,
                    },
                    "attempts": [
                        {
                            "attempt_id": "attempt-SPEC-042-impl-w01-a01",
                            "status": "running",
                        }
                    ],
                }
            ],
            "event_log_file": "events.jsonl",
        }
        (root / "task.yaml").write_text(json.dumps(task), encoding="utf-8")
        (root / "runtime.yaml").write_text(json.dumps(runtime), encoding="utf-8")
        snapshot = {
            "schema_version": "1",
            "event_id": "snapshot-001",
            "event_type": "status-observed",
            "task_id": "SPEC-042",
            "occurred_at": NOW,
            "run_id": RUN_ID,
            "attempt_id": "attempt-SPEC-042-impl-w01-a01",
            "provider": "codex",
            "worker_id": "thread-42",
            "payload": {
                "operation": "inspect",
                "source": "coordinator",
                "timeout_ms": 0,
            },
        }
        (root / "events.jsonl").write_text(
            json.dumps(snapshot) + "\n", encoding="utf-8"
        )

    def authorize(
        self,
        root: Path,
        event_id: str,
        *,
        timeout_ms: int = 30000,
        source: str = "coordinator",
        now: str = NOW,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.authorization_command(
                root,
                event_id,
                timeout_ms=timeout_ms,
                source=source,
                now=now,
            ),
            text=True,
            capture_output=True,
            check=False,
        )

    def authorization_command(
        self,
        root: Path,
        event_id: str,
        *,
        timeout_ms: int = 30000,
        source: str = "coordinator",
        now: str = NOW,
    ) -> list[str]:
        return [
            "python3",
            str(SCRIPT),
            str(root / "task.yaml"),
            "--run-id",
            RUN_ID,
            "--timeout-ms",
            str(timeout_ms),
            "--source",
            source,
            "--event-id",
            event_id,
            "--now",
            now,
            "--write",
        ]

    def test_first_short_wait_is_authorized_and_second_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_bundle(root)
            first = self.authorize(root, "wait-auth-001")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            output = json.loads(first.stdout)
            self.assertEqual(output["native_arguments"]["timeoutMs"], 30000)
            self.assertEqual(
                output["native_arguments"]["targets"][0]["afterCursor"],
                "cursor-8",
            )
            second = self.authorize(
                root,
                "wait-auth-002",
                now="2026-09-01T06:00:01Z",
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("already consumed", second.stderr)
            self.assertEqual(
                len((root / "events.jsonl").read_text(encoding="utf-8").splitlines()),
                2,
            )

    def test_long_or_heartbeat_wait_is_rejected_without_consuming_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_bundle(root)
            long_wait = self.authorize(root, "wait-auth-long", timeout_ms=30001)
            self.assertNotEqual(long_wait.returncode, 0)
            self.assertIn("exceeds 30000", long_wait.stderr)
            heartbeat = self.authorize(
                root,
                "wait-auth-heartbeat",
                source="heartbeat",
            )
            self.assertNotEqual(heartbeat.returncode, 0)
            self.assertIn("Heartbeat cannot authorize", heartbeat.stderr)
            self.assertEqual(
                len((root / "events.jsonl").read_text(encoding="utf-8").splitlines()),
                1,
            )

    def test_concurrent_authorizations_consume_budget_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_bundle(root)
            first = subprocess.Popen(
                self.authorization_command(root, "wait-auth-concurrent-1"),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            second = subprocess.Popen(
                self.authorization_command(root, "wait-auth-concurrent-2"),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            first_output = first.communicate()
            second_output = second.communicate()

            self.assertEqual(sorted([first.returncode, second.returncode]), [0, 1])
            errors = first_output[1] + second_output[1]
            self.assertIn("already consumed", errors)
            self.assertEqual(
                len((root / "events.jsonl").read_text(encoding="utf-8").splitlines()),
                2,
            )

    def test_wait_requires_recorded_zero_wait_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_bundle(root)
            (root / "events.jsonl").write_text("", encoding="utf-8")
            result = self.authorize(root, "wait-auth-001")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("zero-wait snapshot", result.stderr)

    def test_wait_requires_active_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_bundle(root, heartbeat_status="paused")
            result = self.authorize(root, "wait-auth-001")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("heartbeat.status=active", result.stderr)


if __name__ == "__main__":
    unittest.main()

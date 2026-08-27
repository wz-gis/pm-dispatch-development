from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "record_runtime_event.py"
NOW = "2026-07-13T12:00:00Z"


class RuntimeEventCase(unittest.TestCase):
    def run_event(self, root: Path, event_id: str, now: str = NOW) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                str(root / "task.yaml"),
                "--event-id",
                event_id,
                "--event-type",
                "worker-created",
                "--run-id",
                "run-SPEC-042-impl-w01",
                "--provider",
                "codex",
                "--worker-id",
                "thread-42",
                "--payload",
                '{"idempotency_key":"create-SPEC-042-a01"}',
                "--now",
                now,
                "--write",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def make_bundle(self, root: Path) -> None:
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
            "event_log_file": "events.jsonl",
        }
        (root / "task.yaml").write_text(json.dumps(task), encoding="utf-8")
        (root / "runtime.yaml").write_text(json.dumps(runtime), encoding="utf-8")
        (root / "events.jsonl").write_text("", encoding="utf-8")

    def test_appends_validated_event_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_bundle(root)
            result = self.run_event(root, "evt-001")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            lines = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["event_id"], "evt-001")

    def test_rejects_duplicate_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_bundle(root)
            self.assertEqual(self.run_event(root, "evt-001").returncode, 0)
            result = self.run_event(root, "evt-001")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate event_id", result.stderr)


if __name__ == "__main__":
    unittest.main()

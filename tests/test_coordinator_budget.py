from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_coordinator_budget.py"


def load_script():
    spec = importlib.util.spec_from_file_location("pm_coordinator_budget", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def token_line(last_input: int, total_input: int = 200_000) -> str:
    return json.dumps(
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total_input,
                        "cached_input_tokens": total_input - 10_000,
                    },
                    "last_token_usage": {"input_tokens": last_input},
                    "model_context_window": 258_400,
                },
            },
        }
    )


class CoordinatorBudgetCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = load_script()

    def test_high_input_warns_without_requiring_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "rollout-thread-1.jsonl"
            session.write_text(token_line(160_000), encoding="utf-8")
            report = self.script.build_report(session, thread_id="thread-1")
            self.assertEqual(report["action"], "warn")
            self.assertEqual(report["usage"]["last_input_tokens"], 160_000)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--thread-id", "thread-1", "--session", str(session)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["action"], "warn")

    def test_lifetime_records_do_not_block_a_small_current_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "rollout-thread-1.jsonl"
            session.write_text(
                "\n".join(token_line(12_000, index + 1) for index in range(150)),
                encoding="utf-8",
            )
            report = self.script.build_report(session, thread_id="thread-1")
            self.assertEqual(report["action"], "continue")
            self.assertEqual(report["usage"]["model_steps"], 150)

    def test_smaller_latest_input_clears_warning_in_same_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "rollout-thread-1.jsonl"
            session.write_text("\n".join([token_line(180_000)] * 150 + [token_line(12_000)]))
            report = self.script.build_report(session, thread_id="thread-1", epoch=1)
            self.assertEqual(report["action"], "continue")
            self.assertEqual(report["epoch"], 1)

    def test_missing_session_is_explicitly_unknown(self) -> None:
        report = self.script.build_report(None, thread_id="thread-1")
        self.assertEqual(report["action"], "unknown")
        self.assertIsNone(report["usage"])


if __name__ == "__main__":
    unittest.main()

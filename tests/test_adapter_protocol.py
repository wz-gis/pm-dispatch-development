from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "scripts" / "adapter_protocol.py"


def load_protocol():
    spec = importlib.util.spec_from_file_location("pm_adapter_protocol", PROTOCOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AdapterProtocolCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.protocol = load_protocol()
        cls.adapter = json.loads(
            (ROOT / "references" / "adapters" / "external-cli.adapter.json").read_text(
                encoding="utf-8"
            )
        )
        cls.codex_adapter = json.loads(
            (ROOT / "references" / "adapters" / "codex.adapter.json").read_text(
                encoding="utf-8"
            )
        )

    def test_builds_codex_invocation_without_model_override(self) -> None:
        invocation = self.protocol.build_invocation(
            self.codex_adapter,
            "create",
            {
                "title": "SPEC-042 页面",
                "prompt": "implement and verify",
                "reasoning_effort": "high",
            },
            "create-SPEC-042-a01",
        )
        self.assertNotIn("model", invocation["inputs"])
        self.assertEqual(invocation["inputs"]["reasoning_effort"], "high")

    def test_codex_inherited_effort_is_optional(self) -> None:
        invocation = self.protocol.build_invocation(
            self.codex_adapter,
            "create",
            {"title": "BUG-041 修复", "prompt": "implement and verify"},
            "create-BUG-041-a01",
        )
        self.assertEqual(
            invocation["inputs"],
            {"title": "BUG-041 修复", "prompt": "implement and verify"},
        )

    def test_builds_machine_invocation_from_declared_inputs(self) -> None:
        invocation = self.protocol.build_invocation(
            self.adapter,
            "create",
            {
                "title": "SPEC-042 页面",
                "prompt": "implement and verify",
                "reasoning_effort": "deliberate",
            },
            "create-SPEC-042-a01",
        )
        self.assertEqual(invocation["transport"], "command")
        self.assertEqual(invocation["target"], "agent start --json")
        self.assertEqual(invocation["inputs"]["title"], "SPEC-042 页面")
        self.assertEqual(invocation["inputs"]["reasoning_effort"], "deliberate")
        self.assertNotIn("model", invocation)
        self.assertNotIn("model_id", invocation)
        self.assertEqual(invocation["idempotency_key"], "create-SPEC-042-a01")

    def test_rejects_missing_operation_input(self) -> None:
        with self.assertRaisesRegex(self.protocol.AdapterProtocolError, "missing inputs"):
            self.protocol.build_invocation(
                self.adapter,
                "create",
                {"title": "SPEC-042 页面"},
                "create-SPEC-042-a01",
            )

    def test_mutating_operation_requires_idempotency_key(self) -> None:
        with self.assertRaisesRegex(
            self.protocol.AdapterProtocolError, "requires an idempotency key"
        ):
            self.protocol.build_invocation(
                self.codex_adapter,
                "send",
                {"worker_id": "thread-42", "prompt": "continue verification"},
            )

    def test_v2_declares_continuation_and_terminal_operations(self) -> None:
        worker = self.codex_adapter["components"]["worker"]
        for operation in ("send", "wait", "rebind", "collect"):
            self.assertIn(operation, worker)
        invocation = self.protocol.build_invocation(
            self.adapter,
            "rebind",
            {
                "worker_id": "agent-thread:42",
                "continuation_token": "continuation-42",
            },
            "rebind-agent-thread-42",
        )
        self.assertEqual(invocation["protocol_version"], "2")
        self.assertEqual(invocation["target"], "agent resume --json")

    def test_extracts_worker_id_and_status_from_provider_result(self) -> None:
        result = self.protocol.extract_operation_result(
            self.adapter,
            "create",
            {"worker_id": "agent-thread:42", "status": "running"},
        )
        self.assertEqual(result["worker_id"], "agent-thread:42")
        self.assertEqual(result["status"], "running")
        self.assertIsNone(result["continuation_token"])
        self.assertIsNone(result["event_cursor"])

    def test_normalizes_provider_status_and_extracts_terminal_delegation(self) -> None:
        result = self.protocol.extract_operation_result(
            self.adapter,
            "collect",
            {
                "worker_id": "agent-thread:42",
                "status": "completed",
                "continuation_token": "continuation-42",
                "event_cursor": "event-9",
                "delegation": {"summary": "verified"},
            },
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["continuation_token"], "continuation-42")
        self.assertEqual(result["event_cursor"], "event-9")
        self.assertEqual(result["delegation"], {"summary": "verified"})


if __name__ == "__main__":
    unittest.main()

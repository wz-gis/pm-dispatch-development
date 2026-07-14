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

    def test_builds_machine_invocation_from_declared_inputs(self) -> None:
        invocation = self.protocol.build_invocation(
            self.adapter,
            "create",
            {"title": "SPEC-042 页面", "prompt": "implement and verify"},
        )
        self.assertEqual(invocation["transport"], "command")
        self.assertEqual(invocation["target"], "agent start --json")
        self.assertEqual(invocation["inputs"]["title"], "SPEC-042 页面")

    def test_rejects_missing_operation_input(self) -> None:
        with self.assertRaisesRegex(self.protocol.AdapterProtocolError, "missing inputs"):
            self.protocol.build_invocation(self.adapter, "create", {"title": "SPEC-042 页面"})

    def test_extracts_worker_id_and_status_from_provider_result(self) -> None:
        result = self.protocol.extract_operation_result(
            self.adapter,
            "create",
            {"worker_id": "agent-thread:42", "status": "running"},
        )
        self.assertEqual(result, {"worker_id": "agent-thread:42", "status": "running"})


if __name__ == "__main__":
    unittest.main()

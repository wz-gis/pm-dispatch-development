from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "references" / "schemas" / "adapter.schema.json"
ADAPTER_DIR = ROOT / "references" / "adapters"
VALIDATOR_PATH = ROOT / "scripts" / "validate_pm_dispatch.py"

spec = importlib.util.spec_from_file_location("pm_validator", VALIDATOR_PATH)
assert spec and spec.loader
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)


class AdapterContractCase(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_all_machine_adapters_match_adapter_schema(self) -> None:
        paths = sorted(ADAPTER_DIR.glob("*.adapter.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                adapter = json.loads(path.read_text(encoding="utf-8"))
                errors = validator.validate_schema(adapter, self.schema, path.name, self.schema)
                self.assertEqual(errors, [])

    def test_adapter_declares_four_component_contracts(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        self.assertEqual(set(adapter["components"]), {"worker", "model", "monitor", "evidence"})
        self.assertTrue(adapter["components"]["worker"]["create"])
        self.assertTrue(adapter["components"]["worker"]["inspect"])
        self.assertTrue(adapter["components"]["worker"]["cancel"])

    def test_adapter_maps_every_core_reasoning_profile(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        profiles = adapter["models"][0]["reasoning_profiles"]
        self.assertEqual(set(profiles), {"fast", "standard", "deep", "critical"})

    def test_schema_rejects_adapter_without_version(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter.pop("adapter_version", None)
        errors = validator.validate_schema(adapter, self.schema, "adapter", self.schema)
        self.assertTrue(any("adapter_version" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

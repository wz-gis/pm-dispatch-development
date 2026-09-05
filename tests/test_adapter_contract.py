from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
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
        self.assertEqual(
            set(adapter["components"]),
            {"worker", "reasoning", "monitor", "evidence"},
        )
        self.assertEqual(adapter["schema_version"], "3")
        self.assertEqual(adapter["adapter_version"], "13")
        worker = adapter["components"]["worker"]
        self.assertEqual(adapter["protocol_version"], "2")
        self.assertIn(worker["transport"], {"tool", "command", "api", "manual"})
        self.assertEqual(worker["visibility"], "user-visible")
        self.assertEqual(worker["create"]["target"], "create_thread")
        for operation in ("create", "send", "inspect", "wait", "rebind", "collect", "cancel"):
            self.assertTrue(worker[operation]["target"])
            self.assertTrue(worker[operation]["input_fields"])
            self.assertTrue(worker[operation]["result_paths"]["status"])
        self.assertTrue(worker["create"]["result_paths"]["worker_id"])
        self.assertEqual(worker["create"]["idempotency"], "required")
        self.assertEqual(worker["send"]["idempotency"], "required")
        self.assertEqual(worker["rebind"]["idempotency"], "optional")
        self.assertEqual(worker["inspect"]["target"], "wait_threads")
        self.assertEqual(worker["inspect"]["fixed_inputs"], {"timeout_ms": 0})
        self.assertIn("timeout_ms", worker["wait"]["input_fields"])
        self.assertNotIn("timeout_ms", worker["wait"]["optional_input_fields"])
        self.assertEqual(
            worker["wait"]["call_policy"],
            {
                "max_calls_per_run": 1,
                "max_timeout_ms": 30000,
                "allowed_sources": ["coordinator"],
            },
        )
        self.assertEqual(worker["wait"]["timeout_seconds"], 30)
        self.assertTrue(adapter["status_map"])

    def test_adapter_maps_every_core_reasoning_profile(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        profiles = adapter["components"]["reasoning"]["profiles"]
        self.assertEqual(set(profiles), {"fast", "standard", "deep", "critical"})
        self.assertEqual(profiles["standard"], "inherit")
        self.assertEqual(profiles["deep"], "high")
        self.assertNotIn("model", adapter["components"])
        self.assertNotIn("model", adapter["components"]["worker"]["create"]["input_fields"])
        self.assertEqual(
            adapter["components"]["worker"]["create"]["optional_input_fields"],
            ["reasoning_effort"],
        )
        monitor = adapter["components"]["monitor"]
        self.assertEqual(monitor["modes"][0], "heartbeat")
        self.assertEqual(monitor["heartbeat_operation"], "automation_update")
        self.assertEqual(monitor["heartbeat_target"], "coordinator-thread")
        self.assertEqual(monitor["coordinator_binding"], "current-conversation")
        self.assertIn("event-lease", monitor["modes"])
        self.assertEqual(monitor["event_wait_target"], "wait_threads")
        self.assertEqual(monitor["disconnect_probe_operation"], "inspect")
        self.assertEqual(monitor["inspection_interval_seconds"], 600)
        self.assertEqual(monitor["max_inspections_per_cycle"], 1)
        self.assertEqual(monitor["model_free_tick"], "scripts/plan_monitor_tick.py")

    def test_event_lease_adapter_requires_wait_and_watchdog_capabilities(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter["components"]["monitor"]["event_wait_target"] = None
        adapter["capabilities"].remove("lease-watchdog")
        errors = validator.validate_adapter_integrity(adapter, "adapter")
        self.assertTrue(any("event_wait_target" in error for error in errors))
        self.assertTrue(any("lease-watchdog" in error for error in errors))

    def test_heartbeat_adapter_requires_coordinator_thread_target(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter["components"]["monitor"].pop("heartbeat_target")
        errors = validator.validate_adapter_integrity(adapter, "adapter")
        self.assertTrue(any("heartbeat_target=coordinator-thread" in error for error in errors))

    def test_codex_adapter_rejects_internal_worker_or_detached_monitor(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter["components"]["worker"]["visibility"] = "internal"
        adapter["components"]["worker"]["create"]["target"] = "spawn_agent"
        adapter["components"]["monitor"]["heartbeat_operation"] = "create_thread"
        adapter["components"]["monitor"]["coordinator_binding"] = "declared-thread"
        errors = validator.validate_adapter_integrity(adapter, "adapter")
        self.assertTrue(any("user-visible Worker" in error for error in errors))
        self.assertTrue(any("created with create_thread" in error for error in errors))
        self.assertTrue(any("created with automation_update" in error for error in errors))
        self.assertTrue(any("current PM conversation" in error for error in errors))

    def test_codex_adapter_rejects_blocking_inspect_or_implicit_terminal_wait(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter["components"]["worker"]["inspect"]["fixed_inputs"] = {
            "timeout_ms": 120_000
        }
        adapter["components"]["worker"]["wait"]["input_fields"].remove("timeout_ms")
        adapter["components"]["worker"]["wait"]["optional_input_fields"].append(
            "timeout_ms"
        )
        adapter["components"]["worker"]["wait"]["call_policy"]["max_calls_per_run"] = 2
        errors = validator.validate_adapter_integrity(adapter, "adapter")
        self.assertTrue(any("zero-wait" in error for error in errors))
        self.assertTrue(any("explicit timeout_ms" in error for error in errors))
        self.assertTrue(any("single-short" in error for error in errors))

    def test_schema_rejects_adapter_without_version(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter.pop("adapter_version", None)
        errors = validator.validate_schema(adapter, self.schema, "adapter", self.schema)
        self.assertTrue(any("adapter_version" in error for error in errors))

    def test_adapter_integrity_rejects_empty_reasoning_mapping(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter["components"]["reasoning"]["profiles"] = {}
        errors = validator.validate_adapter_integrity(adapter, "adapter")
        self.assertTrue(any("reasoning component" in error for error in errors))

    def test_provider_may_support_subset_of_reasoning_profiles(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter["components"]["reasoning"]["profiles"] = {
            "fast": "max",
            "standard": "max",
        }
        errors = validator.validate_schema(adapter, self.schema, "adapter", self.schema)
        self.assertEqual(errors, [])

    def test_schema_rejects_explicit_model_catalog(self) -> None:
        adapter = json.loads((ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8"))
        adapter["models"] = [{"id": "forbidden-model"}]
        errors = validator.validate_schema(adapter, self.schema, "adapter", self.schema)
        self.assertTrue(
            any(
                ".models: additional property is not allowed" in error
                for error in errors
            )
        )

    def test_malformed_adapter_stops_after_schema_validation(self) -> None:
        malformed = json.loads(
            (ADAPTER_DIR / "codex.adapter.json").read_text(encoding="utf-8")
        )
        malformed["components"]["reasoning"] = ["not-an-object"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "malformed.adapter.json"
            path.write_text(json.dumps(malformed), encoding="utf-8")
            adapters, errors = validator.load_adapters(Path(tmp), self.schema)
        self.assertEqual(adapters, {})
        self.assertTrue(any("expected object" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVER_PATH = ROOT / "scripts" / "resolve_pm_dispatch.py"
CODEX_ADAPTER_PATH = ROOT / "references" / "adapters" / "codex.adapter.json"
NOW = "2026-07-13T12:00:00Z"


def load_resolver():
    spec = importlib.util.spec_from_file_location("pm_resolver", RESOLVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def worker_dispatch() -> dict:
    return {
        "strategy": "single-worker",
        "provider_policy": {"mode": "pinned", "provider": "codex"},
        "required_capabilities": ["background-worker", "code-edit", "git", "heartbeat", "shell"],
        "required_evidence_kinds": ["command", "log"],
        "reasoning_profile": "deep",
        "fallback_policy": {
            "mode": "strict",
            "allowed_providers": ["codex"],
            "allow_manual_monitoring": False,
        },
        "heartbeat_required": True,
    }


class ResolverCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolver = load_resolver()
        codex = json.loads(CODEX_ADAPTER_PATH.read_text(encoding="utf-8"))
        cls.adapters = {"codex": codex}

    def test_pinned_provider_resolves_generic_profile_to_provider_effort(self) -> None:
        resolution = self.resolver.resolve_dispatch(worker_dispatch(), self.adapters, NOW)
        self.assertEqual(resolution["provider"], "codex")
        self.assertIsNone(resolution["model_id"])
        self.assertEqual(resolution["reasoning_profile"], "deep")
        self.assertEqual(resolution["provider_reasoning_effort"], "high")
        self.assertEqual(resolution["monitor_mode"], "heartbeat")
        self.assertIn("heartbeat", resolution["capabilities"])
        self.assertNotIn("lease-watchdog", resolution["capabilities"])
        self.assertNotIn("terminal-event-wait", resolution["capabilities"])

    def test_standard_profile_inherits_model_and_effort(self) -> None:
        dispatch = worker_dispatch()
        dispatch["reasoning_profile"] = "standard"
        resolution = self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)
        self.assertIsNone(resolution["model_id"])
        self.assertEqual(resolution["provider_reasoning_effort"], "inherit")

    def test_visible_codex_worker_without_heartbeat_fails_closed(self) -> None:
        dispatch = worker_dispatch()
        dispatch["heartbeat_required"] = False
        dispatch["required_capabilities"].remove("heartbeat")
        with self.assertRaisesRegex(
            self.resolver.ResolutionError, "no verified parent callback"
        ):
            self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)

    def test_critical_profile_inherits_model_with_high_effort(self) -> None:
        dispatch = worker_dispatch()
        dispatch["reasoning_profile"] = "critical"
        resolution = self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)
        self.assertIsNone(resolution["model_id"])
        self.assertEqual(resolution["provider_reasoning_effort"], "high")

    def test_missing_capability_fails_closed(self) -> None:
        dispatch = worker_dispatch()
        dispatch["required_capabilities"].append("gpu-cluster")
        with self.assertRaisesRegex(self.resolver.ResolutionError, "no compatible provider"):
            self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)

    def test_strict_policy_rejects_auto_provider(self) -> None:
        dispatch = worker_dispatch()
        dispatch["provider_policy"] = {"mode": "auto", "provider": None}
        with self.assertRaisesRegex(self.resolver.ResolutionError, "strict fallback requires a pinned provider"):
            self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)

    def test_compatible_policy_can_record_manual_monitor_fallback(self) -> None:
        external = copy.deepcopy(self.adapters["codex"])
        external.update({"provider": "external-cli", "worker_types": ["agent-thread"]})
        external["components"].pop("model", None)
        external["components"]["worker"]["transport"] = "command"
        external["components"]["worker"]["create"]["target"] = "agent start --json"
        external["components"]["worker"]["inspect"]["target"] = "agent status --json"
        external["components"]["worker"]["cancel"]["target"] = "agent cancel --json"
        external["components"]["monitor"].update(
            {
                "modes": ["manual"],
                "supports_lease_renewal": False,
                "event_wait_target": None,
            }
        )
        dispatch = worker_dispatch()
        dispatch["provider_policy"] = {"mode": "auto", "provider": None}
        dispatch["fallback_policy"].update(
            {
                "mode": "compatible",
                "allowed_providers": ["external-cli"],
                "allow_manual_monitoring": True,
            }
        )
        resolution = self.resolver.resolve_dispatch(
            dispatch, {"external-cli": external}, NOW
        )
        self.assertEqual(resolution["provider"], "external-cli")
        self.assertIsNone(resolution["model_id"])
        self.assertEqual(resolution["monitor_mode"], "manual")

    def test_missing_reasoning_profile_mapping_fails_closed(self) -> None:
        adapter = copy.deepcopy(self.adapters["codex"])
        adapter["components"]["reasoning"]["profiles"].pop("deep")
        with self.assertRaisesRegex(self.resolver.ResolutionError, "no compatible provider"):
            self.resolver.resolve_dispatch(worker_dispatch(), {"codex": adapter}, NOW)

    def test_unsupported_evidence_kind_fails_closed(self) -> None:
        dispatch = worker_dispatch()
        dispatch["required_evidence_kinds"].append("hardware-trace")
        with self.assertRaisesRegex(self.resolver.ResolutionError, "no compatible provider"):
            self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)

    def test_worker_request_rejects_empty_capability_or_evidence_contract(self) -> None:
        dispatch = worker_dispatch()
        dispatch["required_capabilities"] = []
        with self.assertRaisesRegex(self.resolver.ResolutionError, "required_capabilities"):
            self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)

        dispatch = worker_dispatch()
        dispatch["required_evidence_kinds"] = []
        with self.assertRaisesRegex(self.resolver.ResolutionError, "required_evidence_kinds"):
            self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)

    def test_non_codex_machine_adapter_resolves_without_vendor_assumptions(self) -> None:
        external = json.loads(
            (ROOT / "references" / "adapters" / "external-cli.adapter.json").read_text(
                encoding="utf-8"
            )
        )
        dispatch = worker_dispatch()
        dispatch["provider_policy"] = {"mode": "pinned", "provider": "external-cli"}
        dispatch["required_capabilities"].remove("heartbeat")
        dispatch["heartbeat_required"] = False
        dispatch["fallback_policy"].update(
            {"allowed_providers": ["external-cli"], "allow_manual_monitoring": True}
        )
        resolution = self.resolver.resolve_dispatch(
            dispatch, {"external-cli": external}, NOW
        )
        self.assertEqual(resolution["worker_type"], "agent-thread")
        self.assertEqual(resolution["provider_reasoning_effort"], "deliberate")
        self.assertEqual(resolution["monitor_mode"], "poll")

    def test_provider_fallback_can_supply_reasoning_profile(self) -> None:
        codex = copy.deepcopy(self.adapters["codex"])
        codex["components"]["reasoning"]["profiles"].pop("deep")
        external = copy.deepcopy(self.adapters["codex"])
        external.update({"provider": "external-cli", "worker_types": ["agent-thread"]})
        external["components"].pop("model", None)
        dispatch = worker_dispatch()
        dispatch["fallback_policy"].update(
            {"mode": "compatible", "allowed_providers": ["external-cli"]}
        )
        resolution = self.resolver.resolve_dispatch(
            dispatch,
            {"codex": codex, "external-cli": external},
            NOW,
        )
        self.assertEqual(resolution["provider"], "external-cli")

    def test_cli_writes_resolution_to_runtime_for_task_v4(self) -> None:
        task = {
            "schema_version": "4",
            "id": "SPEC-042",
            "runtime_file": "runtime.yaml",
            "dispatch": worker_dispatch(),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task.yaml"
            path.write_text(json.dumps(task), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(RESOLVER_PATH),
                    str(path),
                    "--now",
                    NOW,
                    "--write",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            unchanged_task = json.loads(path.read_text(encoding="utf-8"))
            runtime = json.loads((Path(tmp) / "runtime.yaml").read_text(encoding="utf-8"))
            self.assertNotIn("resolution", unchanged_task["dispatch"])
            self.assertEqual(runtime["resolution"]["provider"], "codex")
            self.assertTrue((Path(tmp) / "events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()

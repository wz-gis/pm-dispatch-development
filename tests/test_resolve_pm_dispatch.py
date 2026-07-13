from __future__ import annotations

import copy
import importlib.util
import json
import sys
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
        "model_request": {
            "quality": "frontier",
            "reasoning_profile": "deep",
            "latency": "normal",
            "cost": "balanced",
        },
        "fallback_policy": {
            "mode": "strict",
            "allowed_providers": ["codex"],
            "allow_model_substitution": False,
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
        self.assertEqual(resolution["model_id"], "gpt-5.6-sol")
        self.assertEqual(resolution["reasoning_profile"], "deep")
        self.assertEqual(resolution["provider_reasoning_effort"], "high")
        self.assertEqual(resolution["monitor_mode"], "heartbeat")

    def test_missing_capability_fails_closed(self) -> None:
        dispatch = worker_dispatch()
        dispatch["required_capabilities"].append("gpu-cluster")
        with self.assertRaisesRegex(self.resolver.ResolutionError, "no compatible provider/model"):
            self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)

    def test_strict_policy_rejects_auto_provider(self) -> None:
        dispatch = worker_dispatch()
        dispatch["provider_policy"] = {"mode": "auto", "provider": None}
        with self.assertRaisesRegex(self.resolver.ResolutionError, "strict fallback requires a pinned provider"):
            self.resolver.resolve_dispatch(dispatch, self.adapters, NOW)

    def test_compatible_policy_can_record_manual_monitor_fallback(self) -> None:
        external = copy.deepcopy(self.adapters["codex"])
        external.update({"provider": "external-cli", "worker_types": ["agent-thread"]})
        external["components"]["worker"].update(
            {"create": "agent start", "inspect": "agent status", "cancel": "agent cancel"}
        )
        external["components"]["monitor"].update(
            {"modes": ["manual"], "supports_lease_renewal": False}
        )
        external["components"]["model"].update(
            {"default_model": "external-frontier", "fallback_models": []}
        )
        external["models"][0].update({"id": "external-frontier", "aliases": []})
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
        self.assertEqual(resolution["monitor_mode"], "manual")

    def test_missing_reasoning_profile_mapping_fails_closed(self) -> None:
        adapter = copy.deepcopy(self.adapters["codex"])
        adapter["models"][0]["reasoning_profiles"].pop("deep")
        with self.assertRaisesRegex(self.resolver.ResolutionError, "no compatible provider/model"):
            self.resolver.resolve_dispatch(worker_dispatch(), {"codex": adapter}, NOW)

    def test_unsupported_evidence_kind_fails_closed(self) -> None:
        dispatch = worker_dispatch()
        dispatch["required_evidence_kinds"].append("hardware-trace")
        with self.assertRaisesRegex(self.resolver.ResolutionError, "no compatible provider/model"):
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


if __name__ == "__main__":
    unittest.main()

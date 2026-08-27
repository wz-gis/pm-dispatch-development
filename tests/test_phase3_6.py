from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PhaseThreeToSixCase(unittest.TestCase):
    def test_evidence_digest_is_bounded_and_detects_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = {
                "schema_version": "3", "id": "SPEC-042",
                "display_name": "SPEC-042 P1 PM 精益上下文", "title": "精益上下文",
                "type": "spec", "priority": "P1", "status": "TRIAGED",
                "mode": "single-project", "area": ["PM"],
                "lifecycle": {"phase": "triage", "owner": "PM", "next_action": "实现"},
                "verification": {"required_levels": ["L1"], "gate_policy": "default", "evidence_file": "evidence.json", "status": "PENDING", "mock_allowed": False, "missing": []},
                "quality_checks": {"policy": "risk-scaled", "checks": []}, "blockers": [],
                "closure": {"status": "open"}, "dependencies": {"requires": [], "blocks": [], "graph_checked_at": "2026-08-27T00:00:00Z"},
                "resources": {"locks": []},
                "dispatch": {"strategy": "direct", "provider_policy": {"mode": "local", "provider": "local"}, "required_capabilities": [], "required_evidence_kinds": [], "reason": "本地", "worker_required": False, "heartbeat_required": False, "selected_at": None, "max_parallel_workers": None, "reasoning_profile": None, "fallback_policy": None, "resolution": None, "autonomy_policy": {"default_action": "proceed", "clarification_policy": "material-irreversible-only", "blocker_policy": "hard-only", "verification_policy": "risk-scaled", "recovery": {"same_method_retries": 1, "alternate_method_attempts": 2, "rediscovery_limit": 1}}, "design_freeze": None, "worker_reuse": None, "batch": None, "heartbeat": None, "escalation_triggers": []},
                "runs": [], "last_updated": "2026-08-27T00:00:00Z",
            }
            evidence = {
                "schema_version": "2", "task_id": "SPEC-042", "generated_at": "2026-08-27T00:00:00Z",
                "verification": {"changed_surface": ["pm"], "original_user_path": "pm", "runtime_shape": "dev", "test_data": [], "levels": {}, "existing_data_regression": "none", "uncovered_items": []},
                "quality_checks": [], "artifacts": {"commands": [], "commits": [], "files_changed": [], "api": [], "sql": [], "browser": [], "screenshots": [], "logs": [], "ids": [], "upgrade_path": [], "release_path": []}, "runs": [], "blockers": [], "conclusion": {"status": "PARTIAL_VERIFIED", "evidence_level": "NONE", "mock_based": False, "real_chain_verified": False, "accepted_fallback": None},
            }
            task_path = root / "task.json"
            evidence_path = root / "evidence.json"
            task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
            evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
            builder = load_module("phase3_digest", "build_evidence_digest.py")
            validator = load_module("phase3_validator", "validate_evidence_digest.py")
            output = root / "ctx" / "current-evidence.json"
            digest, rendered = builder.build_evidence_digest(task_path, output, generated_at="2026-08-27T00:00:00Z")
            self.assertLessEqual(len(rendered), 6000)
            evidence_path.write_text(evidence_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            schema = json.loads((ROOT / "references/schemas/evidence-digest.schema.json").read_text(encoding="utf-8"))
            errors = validator.validate_evidence_digest(digest, digest_path=output, schema=schema, rendered=rendered, check_source=True)
            self.assertTrue(any("source digest drift" in error for error in errors))

    def test_recovery_ledger_opens_after_three_distinct_paths(self) -> None:
        ledger = load_module("phase5_ledger", "manage_recovery_ledger.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = {"schema_version": "3", "id": "BUG-004", "display_name": "BUG-004 P1 PM 修复", "title": "修复", "type": "bug", "priority": "P1", "status": "NEW", "mode": "single-project", "area": ["PM"], "lifecycle": {"phase": "intake", "owner": "PM", "next_action": "修复"}, "verification": {"required_levels": ["L1"], "gate_policy": "x", "evidence_file": "evidence.json", "status": "PENDING", "mock_allowed": False, "missing": []}, "quality_checks": {"policy": "risk-scaled", "checks": []}, "blockers": [], "closure": {"status": "open"}, "dependencies": {"requires": [], "blocks": [], "graph_checked_at": "2026-08-27T00:00:00Z"}, "resources": {"locks": []}, "dispatch": {"strategy": "direct", "provider_policy": {"mode": "local", "provider": "local"}, "required_capabilities": [], "required_evidence_kinds": [], "reason": "本地", "worker_required": False, "heartbeat_required": False, "selected_at": None, "max_parallel_workers": None, "reasoning_profile": None, "fallback_policy": None, "resolution": None, "autonomy_policy": {"default_action": "proceed", "clarification_policy": "material-irreversible-only", "blocker_policy": "hard-only", "verification_policy": "risk-scaled", "recovery": {"same_method_retries": 1, "alternate_method_attempts": 2, "rediscovery_limit": 1}}, "design_freeze": None, "worker_reuse": None, "batch": None, "heartbeat": None, "escalation_triggers": []}, "runs": [], "last_updated": "2026-08-27T00:00:00Z"}
            value = ledger.initial_ledger("BUG-004", "2026-08-27T00:00:00Z")
            entry = ledger.gate_entry(value, "implementation", "sha256:" + "b" * 64)
            for index, method in enumerate(("retry", "isolate", "contract"), start=1):
                entry["failure"] = {"failure_class": "atomic", "fingerprint": "sha256:" + "a" * 64, "diagnosis_status": "confirmed", "checkpoint_ref": None, "next_action": "stop"}
                entry["attempts"].append({"attempt_key": f"a{index}", "failure_fingerprint": "sha256:" + "a" * 64, "method": method, "result": "failed", "artifact_refs": [], "recorded_at": "2026-08-27T00:00:00Z"})
            entry["breaker"]["state"] = "open"
            entry["breaker"]["reason"] = "same Gate and failure fingerprint exhausted three recovery paths"
            failed = ledger.failed_attempts_for(entry, "sha256:" + "a" * 64)
            self.assertEqual(len(failed), 3)
            self.assertEqual(len(set(item["method"] for item in failed)), 3)
            self.assertEqual(ledger.breaker_summary(entry)["remaining_paths"], 0)


if __name__ == "__main__":
    unittest.main()

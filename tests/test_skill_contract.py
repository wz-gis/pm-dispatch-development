from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_pm_dispatch import load_structured_file  # noqa: E402


def schema(name: str) -> dict:
    return json.loads((ROOT / "references" / "schemas" / name).read_text(encoding="utf-8"))


def public_documents() -> list[Path]:
    return [ROOT / "SKILL.md", *ROOT.glob("README*.md"), *ROOT.joinpath("references").rglob("*.md")]


class SkillContractCase(unittest.TestCase):
    def test_documentation_links_resolve_locally(self) -> None:
        for document in public_documents():
            for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                parsed = urlsplit(target.strip("<>"))
                if parsed.scheme or not parsed.path:
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent / unquote(parsed.path)).is_file())

    def test_entrypoint_references_are_discoverable(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        references = re.findall(r"`(references/[^\s`*]+)`", skill)
        self.assertGreaterEqual(len(references), 8)
        for reference in references:
            self.assertTrue((ROOT / reference).is_file(), reference)

    def test_main_skill_stays_within_context_budget(self) -> None:
        self.assertLessEqual(len((ROOT / "SKILL.md").read_bytes()), 5500)

    def test_recovery_policy_preserves_bounded_autonomy(self) -> None:
        policy = schema("task.schema.json")["properties"]["dispatch"]["properties"]["autonomy_policy"]["properties"]
        self.assertEqual(policy["default_action"]["enum"], ["proceed"])
        self.assertEqual(policy["blocker_policy"]["enum"], ["hard-only"])
        self.assertEqual(policy["verification_policy"]["enum"], ["risk-scaled"])
        recovery = policy["recovery"]["properties"]
        self.assertEqual(recovery["same_method_retries"]["maximum"], 1)
        self.assertEqual(recovery["alternate_method_attempts"]["maximum"], 2)
        self.assertEqual(recovery["rediscovery_limit"]["maximum"], 1)

    def test_task_does_not_accept_user_model_selection(self) -> None:
        dispatch = schema("task.schema.json")["properties"]["dispatch"]
        self.assertFalse(dispatch["additionalProperties"])
        self.assertNotIn("model_request", dispatch["properties"])
        self.assertNotIn("model_id", dispatch["properties"])

    def test_codex_workers_use_dispatch_host_default_model(self) -> None:
        adapter = json.loads((ROOT / "references/adapters/codex.adapter.json").read_text())
        self.assertNotIn("model", adapter["components"])
        create = adapter["components"]["worker"]["create"]
        self.assertEqual(create["input_fields"], ["title", "prompt"])
        self.assertEqual(create["optional_input_fields"], ["reasoning_effort"])

    def test_monitoring_uses_bounded_coordinator_heartbeat(self) -> None:
        adapter = json.loads((ROOT / "references/adapters/codex.adapter.json").read_text())
        monitor = adapter["components"]["monitor"]
        self.assertEqual(monitor["coordinator_binding"], "current-conversation")
        self.assertEqual(monitor["inspection_interval_seconds"], 600)
        self.assertEqual(monitor["max_inspections_per_cycle"], 1)
        worker = adapter["components"]["worker"]
        self.assertEqual(worker["inspect"]["fixed_inputs"], {"timeout_ms": 0})
        self.assertEqual(worker["wait"]["call_policy"], {
            "max_calls_per_run": 1, "max_timeout_ms": 30000,
            "allowed_sources": ["coordinator"],
        })

    def test_cross_file_protocol_consistency(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_skill_consistency.py")],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_task_runtime_contract_is_split_and_versioned(self) -> None:
        task = schema("task.schema.json")
        runtime = schema("runtime.schema.json")
        self.assertIn("4", task["properties"]["schema_version"]["enum"])
        self.assertIn("runtime_file", task["properties"])
        self.assertEqual(runtime["properties"]["schema_version"]["enum"], ["1"])
        self.assertIn("continuation_token", runtime["$defs"]["run"]["properties"])
        self.assertIn("event_log_file", runtime["required"])

    def test_dispatch_design_freeze_protects_material_contract(self) -> None:
        freeze = schema("task.schema.json")["properties"]["dispatch"]["properties"]["design_freeze"]
        self.assertTrue({"scope", "constraints", "acceptance", "fingerprint"}.issubset(freeze["required"]))
        self.assertEqual(freeze["properties"]["change_policy"]["enum"], ["material-only-new-attempt"])

    def test_quality_contract_does_not_add_lifecycle_phases(self) -> None:
        task = schema("task.schema.json")
        self.assertIn("quality_checks", task["required"])
        self.assertEqual(task["properties"]["lifecycle"]["properties"]["phase"]["enum"], [
            "intake", "triage", "contract", "implementation", "integration",
            "verification", "closure", "archive",
        ])
        checks = task["properties"]["quality_checks"]["properties"]["checks"]["items"]["properties"]
        self.assertEqual(set(checks["requirement"]["enum"]), {"required", "conditional", "optional"})

    def test_heartbeat_template_fits_machine_budget(self) -> None:
        prompts = (ROOT / "references/prompts.md").read_text(encoding="utf-8")
        heartbeat = prompts.split("## Heartbeat", 1)[1].split("```markdown\n", 1)[1].split("\n```", 1)[0]
        budget = schema("runtime.schema.json")["$defs"]["heartbeat"]["properties"]["prompt_max_chars"]["maximum"]
        self.assertLessEqual(len(heartbeat), budget)
        self.assertIn("wait_threads(timeoutMs=0)", heartbeat)
        self.assertNotIn("timeoutMs=120", heartbeat)

    def test_worker_replacement_requires_a_declared_trigger(self) -> None:
        reuse = schema("task.schema.json")["properties"]["dispatch"]["properties"]["worker_reuse"]
        self.assertTrue({"reuse_across_gates", "replacement_triggers"}.issubset(reuse["required"]))
        triggers = reuse["properties"]["replacement_triggers"]["items"]["enum"]
        self.assertNotIn("gate-transition", triggers)
        self.assertIn("irrecoverable-worker", triggers)

    def test_thin_wrapper_limits_match_task_and_packet(self) -> None:
        task = schema("task.schema.json")["properties"]["dispatch"]["properties"]["delegation"]
        packet = schema("context-packet.schema.json")["properties"]["execution"]["properties"]["delegation"]
        for definition in (task, packet):
            properties = definition["properties"]
            self.assertEqual(properties["initial_invocation_limit"]["enum"], [1])
            self.assertEqual(properties["repair_invocation_limit"]["enum"], [1])
            self.assertEqual(properties["retry_policy"]["enum"], ["focused-verification-failure-only"])

    def test_context_packet_records_provenance(self) -> None:
        packet = schema("context-packet.schema.json")
        self.assertTrue({
            "task", "execution", "confirmed_facts", "source_digests", "packet_sha256",
        }.issubset(packet["required"]))

    def test_published_metrics_have_consistent_denominators(self) -> None:
        report = json.loads((ROOT / "references/usage-baseline.json").read_text())
        self.assertTrue(report["public_aggregate"])
        self.assertEqual(sum(report["task_types"].values()), report["task_count"])
        for denominator, key in (
            ("all_panel_chars", "actionable_vs_all_reduction_pct"),
            ("board_chars", "actionable_vs_board_reduction_pct"),
        ):
            expected = round(100 * (1 - report["actionable_panel_chars"] / report[denominator]), 2)
            self.assertEqual(report[key], expected)
            for name in ("README.md", "README.zh-CN.md", "references/usage-evidence.md"):
                self.assertIn(f"{expected:.2f}%", (ROOT / name).read_text(encoding="utf-8"))
        for name in ("README.md", "README.zh-CN.md", "references/usage-evidence.md"):
            document = (ROOT / name).read_text(encoding="utf-8")
            for key in ("actionable_panel_chars", "all_panel_chars", "board_chars"):
                self.assertIn(f"{report[key]:,}", document)
        self.assertNotIn("tasks_dir", report)
        self.assertNotIn("largest_surfaces", report)

    def test_public_metadata_and_docs_do_not_embed_home_paths(self) -> None:
        metadata = load_structured_file(ROOT / "agents/openai.yaml")["interface"]
        self.assertTrue(25 <= len(metadata["short_description"]) <= 64)
        self.assertIn("$pm-dispatch-development", metadata["default_prompt"])
        self.assertTrue(metadata["display_name"].isascii())
        home_path = re.compile(r"/(?:Users|home)/[^/\s]+")
        for document in public_documents():
            self.assertIsNone(home_path.search(document.read_text(encoding="utf-8")), document.name)


if __name__ == "__main__":
    unittest.main()

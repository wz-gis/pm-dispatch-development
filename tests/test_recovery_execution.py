from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.test_dispatch_preflight import worker_bundle
from tests.test_validate_pm_dispatch import NOW, base_task, frozen_design

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_context_packet import build_context_packet
from dispatch_preflight import run_preflight
from manage_recovery_ledger import default_path, validate_ledger
from validate_context_packet import packet_digest, validate_context_packet
from validate_pm_dispatch import design_freeze_fingerprint, validate_recovery_state

SCHEMAS = ROOT / "references" / "schemas"
FINGERPRINT = "sha256:" + "a" * 64


class RecoveryExecutionCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task_path = self.root / "BUG-041" / "task.json"
        self.task_path.parent.mkdir()
        self.task = base_task()
        self.task["dispatch"]["design_freeze"] = frozen_design()
        self.task["lifecycle"].update(phase="implementation", next_action="Verify the remaining route")
        self.write_task()
        self.schema = json.loads((SCHEMAS / "context-packet.schema.json").read_text())

    def write_task(self) -> None:
        self.task_path.write_text(json.dumps(self.task), encoding="utf-8")

    def cli(self, operation: str, *args: str, code: int = 0):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "manage_recovery_ledger.py"),
             str(self.task_path), operation, "--gate", "implementation", "--now", NOW, *args],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def record(self, key: str, method: str, *, result: str = "failed", code: int = 0, extra=()):
        return self.cli("record", "--attempt-key", key, "--method", method,
                        "--failure-class", "build", "--failure-fingerprint", FINGERPRINT,
                        "--result", result, "--next-action", "Repair one failing check", *extra, code=code)

    def authorize(self, key: str, method: str, code: int = 0):
        return self.cli("authorize", "--attempt-key", key, "--method", method, code=code)

    def ledger(self) -> dict:
        return json.loads(default_path(self.task_path).read_text())

    def open_breaker(self) -> None:
        self.record("a1", "retry")
        self.authorize("a2", "isolate")
        self.record("a2", "isolate")
        self.authorize("a3", "repair-contract")
        self.record("a3", "repair-contract", code=2)

    def packet(self, **kwargs):
        return build_context_packet(self.task_path, self.root / "packet.json", gate="implementation", **kwargs)

    def preflight(self, output: str, **kwargs):
        return run_preflight(
            self.task_path, project_root=self.root, output_dir=self.root / output,
            gate="implementation", focus=[], verification_commands=[], max_chars=12000,
            max_files=100, generated_at=NOW, **kwargs,
        )

    def test_breaker_is_enforced_across_preflight_directories(self) -> None:
        self.open_breaker()
        before = default_path(self.task_path).read_bytes()
        for directory in ("dispatch-1", "dispatch-2"):
            with self.assertRaisesRegex(ValueError, "circuit breaker is open"):
                self.preflight(directory)
            self.assertFalse((self.root / directory / "recovery-ledger.json").exists())
        self.assertEqual(before, default_path(self.task_path).read_bytes())
        with self.assertRaisesRegex(ValueError, "circuit breaker is open"):
            self.packet()

    def test_reservation_is_required_and_same_method_is_bounded_before_execution(self) -> None:
        self.record("a1", "retry")
        with self.assertRaisesRegex(ValueError, "requires authorize"):
            self.packet()
        self.authorize("a2", "retry")
        self.authorize("a2", "retry", code=1)
        self.authorize("a3", "isolate", code=1)
        packet, _ = self.packet(recovery_attempt="a2", mode="continuation")
        self.assertEqual(packet["objective"], "Verify the remaining route")
        self.record("a2", "retry")
        self.authorize("a3", "retry", code=1)
        self.record("unreserved", "isolate", code=1)
        self.authorize("a3", "isolate")
        self.record("a3", "isolate", result="recovered")
        packet, _ = self.packet(mode="continuation")
        self.assertIsNone(packet["open_failure"])

    def test_authorize_is_atomic_across_processes(self) -> None:
        self.record("a1", "retry")
        command = [sys.executable, str(ROOT / "scripts" / "manage_recovery_ledger.py"),
                   str(self.task_path), "authorize", "--gate", "implementation", "--method", "isolate"]
        processes = [subprocess.Popen(command + ["--attempt-key", key], stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for key in ("a2", "a3")]
        for process in processes:
            process.communicate(timeout=10)
        self.assertEqual(sorted(process.returncode for process in processes), [0, 1])
        pending = [row for row in self.ledger()["gates"][0]["attempts"] if row["result"] == "pending"]
        self.assertEqual(len(pending), 1)

    def test_validator_checks_canonical_ledger_even_if_packet_hides_it(self) -> None:
        self.open_breaker()
        packet, _ = self.packet(purpose="inspect")
        packet["purpose"] = "execute"
        packet["recovery"] = None
        packet["source_digests"]["recovery_ledger"] = None
        packet["packet_sha256"] = packet_digest(packet)
        errors = validate_context_packet(packet, packet_path=self.root / "packet.json", schema=self.schema)
        self.assertTrue(any("circuit breaker is open" in error for error in errors), errors)

    def test_inspection_remains_possible_but_cannot_dispatch(self) -> None:
        self.open_breaker()
        packet, _ = self.packet(purpose="inspect")
        errors = validate_context_packet(packet, packet_path=self.root / "packet.json", schema=self.schema)
        self.assertEqual(errors, [])
        errors = validate_context_packet(packet, packet_path=self.root / "packet.json", schema=self.schema, prompt_text="continue")
        self.assertTrue(any("executable packet" in error for error in errors), errors)
        report = self.preflight("inspection", purpose="inspect")
        self.assertEqual(Path(report["recovery_ledger"]), default_path(self.task_path))

    def test_reset_requires_change_and_evidence_not_magic_words(self) -> None:
        self.open_breaker()
        proof = self.root / "review.txt"
        proof.write_text("Reviewed the frozen contract", encoding="utf-8")
        self.cli("reset", "--reason", "contract unchanged", "--artifact-ref", str(proof), code=1)
        self.cli("reset", "--reason", "design", "--design-fingerprint", "sha256:" + "b" * 64,
                 "--artifact-ref", str(proof), code=1)
        self.task["dispatch"]["design_freeze"]["constraints"].append("Changed protected boundary")
        freeze = self.task["dispatch"]["design_freeze"]
        freeze["fingerprint"] = design_freeze_fingerprint(freeze)
        self.write_task()
        self.cli("reset", "--reason", "accepted boundary change", "--artifact-ref", str(proof))
        entry = self.ledger()["gates"][0]
        self.assertEqual(len(entry["attempts"]), 3)
        self.assertEqual(entry["resets"][0]["after_attempt"], 3)
        self.record("a4", "retry")
        self.assertEqual(self.ledger()["gates"][0]["breaker"]["state"], "closed")

    def test_changed_recorded_checkpoint_can_reset_but_missing_proof_cannot(self) -> None:
        checkpoint = self.task_path.parent / "checkpoint.txt"
        checkpoint.write_text("old environment", encoding="utf-8")
        self.record("a1", "retry", extra=("--checkpoint-ref", "checkpoint.txt"))
        self.cli("reset", "--reason", "environment repaired", "--artifact-ref", "checkpoint.txt", code=1)
        checkpoint.write_text("verified repaired environment", encoding="utf-8")
        self.cli("reset", "--reason", "environment repaired", "--artifact-ref", "missing.txt", code=1)
        self.cli("reset", "--reason", "environment repaired", "--artifact-ref", "checkpoint.txt")
        self.assertEqual(self.ledger()["gates"][0]["resets"][0]["kind"], "checkpoint")

    def test_legacy_import_preserves_history_without_overwriting_canonical(self) -> None:
        self.record("a1", "retry")
        legacy = self.root / "legacy-ledger.json"
        legacy.write_text(json.dumps(self.ledger()), encoding="utf-8")
        self.cli("init", "--ledger", str(legacy), code=1)
        self.cli("import", "--import-ledger", str(legacy), code=1)
        default_path(self.task_path).unlink()
        self.cli("import", "--import-ledger", str(legacy))
        self.assertEqual(len(self.ledger()["gates"][0]["attempts"]), 1)

    def test_fingerprint_and_diagnosis_cannot_hide_unresolved_failure(self) -> None:
        self.record("a1", "retry")
        self.authorize("a2", "isolate")
        self.cli("record", "--attempt-key", "a2", "--method", "isolate", "--failure-class", "build",
                 "--failure-fingerprint", "sha256:" + "b" * 64, "--result", "failed", code=1)
        self.record("a2", "isolate", extra=("--diagnosis-status", "resolved"), code=1)
        with self.assertRaisesRegex(ValueError, "changing Gate"):
            build_context_packet(self.task_path, self.root / "other.json", gate="verification", recovery_attempt="a2")

    def test_main_validator_rejects_open_breaker_on_active_run(self) -> None:
        self.open_breaker()
        active = copy.deepcopy(self.task)
        active["runs"] = [{"run_id": "run-1", "status": "running", "gate": "implementation"}]
        errors = validate_recovery_state(SimpleNamespace(path=self.task_path, task=active))
        self.assertTrue(any("circuit breaker is open" in error for error in errors), errors)

    def test_schema_detects_exhausted_ledger_with_forged_closed_state(self) -> None:
        self.open_breaker()
        ledger = self.ledger()
        ledger["gates"][0]["breaker"]["state"] = "closed"
        errors = validate_ledger(ledger, default_path(self.task_path), SCHEMAS)
        self.assertTrue(any("require an open breaker" in error for error in errors), errors)

    def test_continuation_never_falls_back_to_full_scope(self) -> None:
        self.task["lifecycle"]["accepted_scope"] = "Implement all twenty-two features"
        self.task["lifecycle"]["next_action"] = ""
        self.write_task()
        with self.assertRaisesRegex(ValueError, "continuation requires"):
            self.packet(mode="continuation")
        packet, _ = self.packet(mode="continuation", objective="One browser check")
        self.assertEqual(packet["objective"], "One browser check")

    def test_worker_reuse_preflight_defaults_to_delta(self) -> None:
        task, runtime = worker_bundle()
        task["lifecycle"].update(accepted_scope="Implement all twenty-two features", next_action="One browser check")
        self.task = task
        self.write_task()
        (self.task_path.parent / "runtime.yaml").write_text(json.dumps(runtime), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reconcile/import legacy history"):
            self.preflight("missing-ledger")
        with self.assertRaisesRegex(ValueError, "reconcile/import legacy history"):
            self.packet(mode="continuation")
        report = self.preflight("read-only-missing-ledger", purpose="inspect")
        self.assertIsNone(report["recovery_ledger"])
        self.assertFalse(default_path(self.task_path).exists())
        self.cli("init")
        result = self.preflight("repair-1")
        packet = json.loads((self.root / "repair-1" / "active-context.json").read_text())
        self.assertEqual(result["mode"], "continuation")
        self.assertEqual(packet["objective"], "One browser check")

    def test_preflight_does_not_ignore_legacy_history_in_its_output_directory(self) -> None:
        self.record("a1", "retry")
        output = self.root / "legacy-output"
        output.mkdir()
        (output / "recovery-ledger.json").write_bytes(default_path(self.task_path).read_bytes())
        default_path(self.task_path).unlink()
        with self.assertRaisesRegex(ValueError, "legacy recovery history"):
            self.preflight("legacy-output")
        self.assertFalse(default_path(self.task_path).exists())


if __name__ == "__main__":
    unittest.main()

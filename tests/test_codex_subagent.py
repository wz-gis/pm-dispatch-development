from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapter_protocol import build_invocation, extract_operation_result
from authorize_terminal_wait import authorize_terminal_wait
from dispatch_preflight import run_preflight
from manage_dispatch_transaction import begin, complete, rollback
from resolve_pm_dispatch import resolve_dispatch
from select_codex_execution import TOOL_SETS, select_execution
from validate_pm_dispatch import load_adapters, load_structured_file, parse_time, validate_schema, validate_adapter_resolution
from tests.test_dispatch_transaction import provisioning_bundle
from tests.test_validate_pm_dispatch import base_task, codex_dispatch, split_runtime
from tests import test_validate_pm_dispatch as validator_tests

NOW = "2026-07-13T12:00:00Z"
ADAPTER = json.loads((ROOT / "references/adapters/codex-subagent.adapter.json").read_text())
TOOLS = ["multi_agent_v1__" + name for name in TOOL_SETS["codex-subagent"]]


def dispatch():
    value = codex_dispatch()
    value.update(provider_policy={"mode": "pinned", "provider": "codex-subagent"},
                 heartbeat_required=False, required_capabilities=["code-edit", "shell"],
                 required_evidence_kinds=["command"], heartbeat=None)
    value["fallback_policy"]["allowed_providers"] = ["codex-subagent"]
    value["resolution"] = resolve_dispatch(value, {"codex-subagent": ADAPTER}, NOW, TOOLS)
    return value


def runtime_bundle():
    runtime = provisioning_bundle()
    runtime["resolution"] = dispatch()["resolution"]
    runtime["heartbeat"] = None
    run = runtime["runs"][0]
    for key in ("provider", "adapter_version", "worker_type", "model_id", "reasoning_profile", "provider_reasoning_effort"):
        run[key] = runtime["resolution"][key]
    run.pop("inspection_budget", None)
    return runtime, run


class CodexSubagentCase(unittest.TestCase):
    def test_full_validator_and_preflight_accept_native_run(self):
        runtime, run = runtime_bundle()
        task = base_task("SPEC-101")
        task.update(status="IN_IMPL", type="spec", display_name="SPEC-101 P1 AA Add page", title="Add page")
        run["worker_label"] = "SPEC-101 P1 AA Add page [impl w01]"
        task["lifecycle"]["phase"] = "implementation"
        task["dispatch"] = dispatch()
        task["runs"] = [run]
        task, _ = split_runtime(task)
        begin(runtime, run, transaction_id="tx-1", now=parse_time(NOW), ttl_seconds=120)
        result = validator_tests.ValidatorCase().run_task(task, runtime=runtime)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        def wait_event(event_id):
            return {"schema_version": "1", "event_id": event_id,
                    "event_type": "terminal-wait-authorized", "task_id": task["id"],
                    "occurred_at": NOW, "run_id": run["run_id"],
                    "attempt_id": run["attempts"][0]["attempt_id"], "provider": "codex-subagent",
                    "worker_id": "agent-1", "payload": {"source": "coordinator", "timeout_ms": 30000}}

        complete(runtime, run, transaction_id="tx-1", worker_id="agent-1", now=parse_time(NOW), lease_seconds=3600)
        accepted = validator_tests.ValidatorCase().run_task(task, runtime=runtime, runtime_events=[wait_event("auth-1")])
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        duplicate = validator_tests.ValidatorCase().run_task(task, runtime=runtime, runtime_events=[wait_event("auth-1"), wait_event("auth-2")])
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("consumed 2 terminal waits", duplicate.stdout + duplicate.stderr)
        # Test creation Preflight against a separate not-yet-created Run.
        runtime, run = runtime_bundle()
        run["worker_label"] = "SPEC-101 P1 AA Add page [impl w01]"
        begin(runtime, run, transaction_id="tx-1", now=parse_time(NOW), ttl_seconds=120)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "task.yaml"
            path.write_text(json.dumps(task))
            (root / "runtime.yaml").write_text(json.dumps(runtime))
            (root / "events.jsonl").write_text("")
            kwargs = dict(project_root=root, output_dir=root / "context", gate="implementation", focus=[],
                          verification_commands=["python3 -m unittest"], max_chars=6000, max_files=100,
                          generated_at=NOW, host_tools=TOOLS)
            result = run_preflight(path, **kwargs)
            self.assertTrue(result["context_packet"])
            self.assertIsNone(result["heartbeat"])
            with self.assertRaisesRegex(ValueError, "unavailable host tools"):
                run_preflight(path, **(kwargs | {"host_tools": []}))
            # Resolver must not silently move this pending Worker to another transport.
            visible = copy.deepcopy(task)
            visible["dispatch"]["provider_policy"]["provider"] = "codex"
            visible["dispatch"]["fallback_policy"]["allowed_providers"] = ["codex"]
            visible["dispatch"]["heartbeat_required"] = True
            path.write_text(json.dumps(visible))
            before = (root / "runtime.yaml").read_bytes()
            changed = subprocess.run([sys.executable, str(ROOT / "scripts/resolve_pm_dispatch.py"),
                                      str(path), "--write"], capture_output=True, text=True)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("cannot change execution path", changed.stderr)
            self.assertEqual((root / "runtime.yaml").read_bytes(), before)
        complete(runtime, run, transaction_id="tx-1", worker_id="agent-1", now=parse_time(NOW), lease_seconds=3600)
        result = validator_tests.ValidatorCase().run_task(task, runtime=runtime)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_internal_only_selects_without_visible_tools(self):
        result = select_execution(TOOLS, completion_notifications=True)
        self.assertEqual(result["provider"], "codex-subagent")
        self.assertEqual(result["visibility"], "internal")
        self.assertFalse(result["heartbeat_required"])

    def test_no_callback_or_partial_tools_do_not_claim_delegation(self):
        self.assertEqual(select_execution(TOOLS)["action"], "direct")
        self.assertEqual(select_execution(TOOLS[:-1], completion_notifications=True)["action"], "direct")
        self.assertEqual(select_execution(["spawn_agent", "send_message", "wait", "close_agent"], completion_notifications=True)["action"], "bind-host-tools")

    def test_visible_requirement_is_never_silently_downgraded(self):
        self.assertEqual(select_execution(TOOLS, require_visible=True, completion_notifications=True)["action"], "unavailable")
        result = select_execution(TOOLS + list(TOOL_SETS["codex"]), require_visible=True)
        self.assertEqual(result["provider"], "codex")

    def test_resolver_checks_actual_tools_and_preserves_requirements(self):
        value = dispatch()
        self.assertEqual(value["resolution"]["monitor_mode"], "milestone")
        errors = []
        validate_adapter_resolution({"dispatch": value, "runs": []}, {"codex-subagent": ADAPTER}, errors, "task")
        self.assertEqual(errors, [])
        with self.assertRaisesRegex(ValueError, "unavailable host tools"):
            resolve_dispatch(value, {"codex-subagent": ADAPTER}, NOW, [])
        value["heartbeat_required"] = True
        with self.assertRaisesRegex(ValueError, "cannot satisfy periodic"):
            resolve_dispatch(value, {"codex-subagent": ADAPTER}, NOW, TOOLS)
        value["heartbeat_required"] = False
        value["required_capabilities"].append("heartbeat")
        with self.assertRaisesRegex(ValueError, "cannot satisfy periodic"):
            resolve_dispatch(value, {"codex-subagent": ADAPTER}, NOW, TOOLS)
        value["required_capabilities"].remove("heartbeat")
        value["required_capabilities"].append("background-worker")
        with self.assertRaisesRegex(ValueError, "missing capabilities"):
            resolve_dispatch(value, {"codex-subagent": ADAPTER}, NOW, TOOLS)

    def test_catalog_and_native_envelopes(self):
        schema = load_structured_file(ROOT / "references/schemas/adapter.schema.json")
        adapters, errors = load_adapters(ROOT / "references/adapters", schema)
        self.assertEqual(errors, [])
        self.assertIn("codex-subagent", adapters)
        create = build_invocation(ADAPTER, "create", {"prompt": "bounded task"}, "create-1")
        self.assertEqual(create["native_arguments"], {"message": "bounded task"})
        sent = build_invocation(ADAPTER, "send", {"worker_id": "agent-1", "prompt": "repair"}, "send-1")
        self.assertEqual(sent["native_arguments"], {"target": "agent-1", "message": "repair"})
        for name in ("inspect", "rebind", "collect"):
            with self.assertRaisesRegex(ValueError, "not supported"):
                build_invocation(ADAPTER, name, {"worker_id": "agent-1"})
        for timeout in (0, 9999, 30001, 120000, True):
            with self.assertRaises(ValueError):
                build_invocation(ADAPTER, "wait", {"worker_id": "agent-1", "timeout_ms": timeout})

    def test_native_result_identity_timeout_and_closure(self):
        created = extract_operation_result(ADAPTER, "create", {"agent_id": "agent-1", "nickname": "worker"})
        self.assertEqual(created["worker_id"], "agent-1")
        completed = extract_operation_result(ADAPTER, "collect", {"status": {"agent-1": {"completed": "evidence"}}}, "agent-1")
        self.assertEqual(completed["delegation"], "evidence")
        self.assertTrue(completed["requires_acceptance"])
        for payload in ({"status": {}, "timed_out": True}, {"status": {"agent-1": "not_found"}}, {"status": {"agent-1": "interrupted"}}):
            result = extract_operation_result(ADAPTER, "wait", payload, "agent-1")
            self.assertEqual(result["status"], "unknown")
            self.assertTrue(result["requires_reconciliation"])
        with self.assertRaisesRegex(ValueError, "does not match"):
            extract_operation_result(ADAPTER, "wait", {"status": {"agent-2": {"completed": "wrong"}}}, "agent-1")
        closed = extract_operation_result(ADAPTER, "cancel", {"previous_status": "running"}, "agent-1")
        self.assertEqual(closed["status"], "unknown")

    def test_provisioning_without_heartbeat_retains_lease_and_budget(self):
        runtime, run = runtime_bundle()
        begin(runtime, run, transaction_id="tx-1", now=parse_time(NOW), ttl_seconds=120)
        self.assertEqual(run["wait_budget"]["max_calls"], 1)
        self.assertNotIn("inspection_budget", run)
        complete(runtime, run, transaction_id="tx-1", worker_id="agent-1", now=parse_time(NOW), lease_seconds=3600)
        self.assertEqual(run["attempts"][0]["lease"]["holder"], run["run_id"])
        schema = load_structured_file(ROOT / "references/schemas/runtime.schema.json")
        self.assertEqual(validate_schema(runtime, schema, "runtime", schema), [])

    def test_failed_provisioning_does_not_demand_nonexistent_automation(self):
        runtime, run = runtime_bundle()
        begin(runtime, run, transaction_id="tx-1", now=parse_time(NOW), ttl_seconds=120)
        rollback(runtime, run, transaction_id="tx-1", failure="confirmed spawn failure", now=parse_time(NOW), heartbeat_stopped=False)
        self.assertEqual(run["status"], "cancelled")

    def test_native_wait_budget_is_atomic_and_needs_no_snapshot(self):
        runtime, run = runtime_bundle()
        begin(runtime, run, transaction_id="tx-1", now=parse_time(NOW), ttl_seconds=120)
        complete(runtime, run, transaction_id="tx-1", worker_id="agent-1", now=parse_time(NOW), lease_seconds=3600)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text(json.dumps(runtime))
            events = Path(directory) / "events.jsonl"
            events.write_text("")
            kwargs = dict(run_id=run["run_id"], source="coordinator", occurred_at=NOW,
                          adapter=ADAPTER, event_schema=load_structured_file(ROOT / "references/schemas/runtime-event.schema.json"), write=True)
            for timeout in (0, 9999, 30001, 120000):
                with self.assertRaises(ValueError):
                    authorize_terminal_wait(path, event_id="bad", timeout_ms=timeout, **kwargs)
            with self.assertRaisesRegex(ValueError, "Heartbeat cannot"):
                authorize_terminal_wait(path, event_id="bad", timeout_ms=30000, **(kwargs | {"source": "heartbeat"}))
            self.assertEqual(events.read_text(), "")
            result = authorize_terminal_wait(path, event_id="wait-1", timeout_ms=30000, **kwargs)
            self.assertEqual(result["native_arguments"], {"targets": ["agent-1"], "timeout_ms": 30000})
            with self.assertRaisesRegex(ValueError, "already consumed"):
                authorize_terminal_wait(path, event_id="wait-2", timeout_ms=10000, **kwargs)
            self.assertEqual(len(events.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()

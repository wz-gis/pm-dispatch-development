"""Alternate-host fixtures use synthetic parameter names, not inferred live schemas."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapter_protocol import build_invocation, extract_operation_result
from select_codex_execution import missing_tools, native_bindings, select_execution
from tests.test_codex_subagent import ADAPTER, NOW, dispatch, runtime_bundle
from authorize_terminal_wait import authorize_terminal_wait
from manage_dispatch_transaction import begin, complete
from validate_pm_dispatch import load_structured_file, parse_time
from resolve_pm_dispatch import resolve_dispatch


def alternate_host():
    # These fields deliberately differ from send_input's target/message signature.
    return {"tools": ["host.spawn_agent", "host.followup_task", "host.interrupt_agent"],
            "native_agent_bindings": {
                "send": {"tool": "host.followup_task", "schema_verified": True,
                         "input_map": {"worker_id": "recipient", "prompt": "task_text"},
                         "result_paths": {"submission_id": "$.receipt_id"}},
                "interrupt": {"tool": "host.interrupt_agent", "schema_verified": True,
                              "input_map": {"worker_id": "recipient"}}}}


class NativeToolBindingCase(unittest.TestCase):
    def test_alternate_names_request_binding_not_direct(self):
        route = select_execution(alternate_host()["tools"], completion_notifications=True)
        self.assertEqual(route["provider"], "codex-subagent")
        self.assertEqual(route["action"], "bind-host-tools")
        self.assertFalse(route["optional_operations"]["cancel"])

    def test_bound_followup_without_close_or_wait_is_ready(self):
        host = alternate_host()
        route = select_execution(host, completion_notifications=True)
        self.assertEqual(route["action"], "ready")
        self.assertEqual(route["tools"]["send"], "host.followup_task")
        self.assertEqual(route["optional_operations"], {"wait": False, "cancel": False, "interrupt": True})
        resolution = resolve_dispatch(dispatch(), {"codex-subagent": ADAPTER}, NOW, host)
        self.assertEqual(resolution["monitor_mode"], "milestone")

    def test_legacy_host_does_not_require_close(self):
        route = select_execution(["spawn_agent", "send_input"], completion_notifications=True)
        self.assertEqual(route["action"], "ready")

    def test_verified_role_binding_can_describe_another_host_name(self):
        host = alternate_host()
        host["tools"][1] = "host.continue_work"
        host["native_agent_bindings"]["send"]["tool"] = "host.continue_work"
        route = select_execution(host, completion_notifications=True)
        self.assertEqual(route["action"], "ready")
        self.assertEqual(route["tools"]["send"], "host.continue_work")

    def test_native_send_builds_verified_arguments_and_decodes_receipt(self):
        host = alternate_host()
        invocation = build_invocation(ADAPTER, "send", {"worker_id": "worker-1", "prompt": "repair"},
                                      "send-1", host_tools=host)
        self.assertEqual(invocation["target"], "host.followup_task")
        self.assertEqual(invocation["native_arguments"], {"recipient": "worker-1", "task_text": "repair"})
        result = extract_operation_result(ADAPTER, "send", {"receipt_id": "submission-1"}, "worker-1", host)
        self.assertEqual(result["submission_id"], "submission-1")
        self.assertEqual(result["status"], "unknown")

    def test_unknown_schema_never_builds_guessed_arguments(self):
        with self.assertRaisesRegex(ValueError, "no verified host binding"):
            build_invocation(ADAPTER, "send", {"worker_id": "worker-1", "prompt": "repair"},
                             "send-1", host_tools=alternate_host()["tools"])
        with self.assertRaisesRegex(ValueError, "bind-host-tools"):
            resolve_dispatch(dispatch(), {"codex-subagent": ADAPTER}, NOW, alternate_host()["tools"])

    def test_interrupt_is_not_close_or_implicit_send_interrupt(self):
        host = alternate_host()
        with self.assertRaisesRegex(ValueError, "no verified host binding"):
            build_invocation(ADAPTER, "cancel", {"worker_id": "worker-1"}, "cancel-1", host_tools=host)
        with self.assertRaisesRegex(ValueError, "does not map inputs"):
            build_invocation(ADAPTER, "send", {"worker_id": "worker-1", "prompt": "repair", "interrupt": True},
                             "send-1", host_tools=host)
        host["native_agent_bindings"]["cancel"] = host["native_agent_bindings"]["interrupt"]
        with self.assertRaisesRegex(ValueError, "interrupt is not close"):
            native_bindings(host)

    def test_invalid_bindings_are_rejected(self):
        for mutation in ("unverified", "missing-tool", "collision", "model-field"):
            host = alternate_host()
            send = host["native_agent_bindings"]["send"]
            if mutation == "unverified":
                send["schema_verified"] = False
            elif mutation == "missing-tool":
                send["tool"] = "other.followup_task"
            elif mutation == "collision":
                send["input_map"]["prompt"] = "recipient"
            else:
                send["input_map"]["model"] = "model"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                native_bindings(host)

    def test_explicit_wait_capability_is_not_silently_dropped(self):
        self.assertTrue(missing_tools("codex-subagent", alternate_host(), ["terminal-event-wait"]))
        value = dispatch()
        value["required_capabilities"].append("terminal-event-wait")
        with self.assertRaisesRegex(ValueError, "missing-required-terminal-event-wait"):
            resolve_dispatch(value, {"codex-subagent": ADAPTER}, NOW, alternate_host())

    def test_unavailable_wait_does_not_consume_budget(self):
        runtime, run = runtime_bundle()
        begin(runtime, run, transaction_id="tx-1", now=parse_time(NOW), ttl_seconds=120)
        complete(runtime, run, transaction_id="tx-1", worker_id="agent-1", now=parse_time(NOW), lease_seconds=3600)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "runtime.json"
            path.write_text(json.dumps(runtime))
            events = root / "events.jsonl"
            events.write_text("")
            with self.assertRaisesRegex(ValueError, "no verified host binding"):
                authorize_terminal_wait(path, run_id=run["run_id"], source="coordinator", occurred_at=NOW,
                    adapter=ADAPTER, event_schema=load_structured_file(ROOT / "references/schemas/runtime-event.schema.json"),
                    write=True, timeout_ms=30000, event_id="wait-1", host_tools=alternate_host())
            self.assertEqual(events.read_text(), "")

    def test_cli_uses_same_binding_for_selection_and_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "host-tools.json"
            inventory.write_text(json.dumps(alternate_host()))
            route = subprocess.run([sys.executable, str(ROOT / "scripts/select_codex_execution.py"),
                                    "--tools", str(inventory), "--completion-notifications"], capture_output=True, text=True)
            self.assertEqual(route.returncode, 0, route.stderr)
            self.assertEqual(json.loads(route.stdout)["action"], "ready")
            call = subprocess.run([sys.executable, str(ROOT / "scripts/adapter_protocol.py"),
                                   str(ROOT / "references/adapters/codex-subagent.adapter.json"), "send",
                                   "--inputs", json.dumps({"worker_id": "w-1", "prompt": "repair"}),
                                   "--idempotency-key", "send-1", "--host-tools", str(inventory)], capture_output=True, text=True)
            self.assertEqual(call.returncode, 0, call.stderr)
            self.assertEqual(json.loads(call.stdout)["target"], "host.followup_task")


if __name__ == "__main__":
    unittest.main()

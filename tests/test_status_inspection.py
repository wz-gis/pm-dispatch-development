from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from tests.test_validate_pm_dispatch import (
    base_task,
    codex_dispatch,
    codex_run,
    split_runtime,
)


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZE = ROOT / "scripts" / "authorize_status_inspect.py"
PLANNER = ROOT / "scripts" / "plan_monitor_tick.py"
COMPLETER = ROOT / "scripts" / "complete_status_inspect.py"
NOW = "2026-07-13T12:00:00Z"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def worker_bundle() -> tuple[dict, dict]:
    task = base_task("SPEC-101")
    task.update({"status": "IN_IMPL", "type": "spec"})
    task["lifecycle"]["phase"] = "implementation"
    task["dispatch"] = codex_dispatch()
    task["runs"] = [codex_run()]
    return split_runtime(task)


class StatusInspectionCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authorizer = load_module("pm_status_inspect", AUTHORIZE)
        cls.planner = load_module("pm_monitor_tick", PLANNER)
        cls.completer = load_module("pm_complete_status_inspect", COMPLETER)
        cls.adapter = json.loads(
            (ROOT / "references" / "adapters" / "codex.adapter.json").read_text()
        )
        cls.event_schema = json.loads(
            (ROOT / "references" / "schemas" / "runtime-event.schema.json").read_text()
        )

    def make_runtime(self, root: Path) -> tuple[Path, dict]:
        _, runtime = worker_bundle()
        path = root / "runtime.json"
        path.write_text(json.dumps(runtime), encoding="utf-8")
        (root / "events.jsonl").write_text("", encoding="utf-8")
        return path, runtime

    def authorize(
        self,
        path: Path,
        *,
        event_id: str,
        cycle_id: str,
        now: str,
        reason: str = "scheduled",
        source: str = "coordinator",
    ):
        return self.authorizer.authorize_status_inspect(
            path,
            run_id="run-SPEC-101-impl-w01",
            source=source,
            reason=reason,
            cycle_id=cycle_id,
            event_id=event_id,
            occurred_at=now,
            adapter=self.adapter,
            event_schema=self.event_schema,
            write=True,
        )

    def test_one_snapshot_per_cycle_and_ten_minute_debounce(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.make_runtime(Path(directory))
            result = self.authorize(
                path,
                event_id="inspect-001",
                cycle_id="cycle-001",
                now=NOW,
                reason="post-create",
            )
            self.assertEqual(result["native_arguments"]["timeoutMs"], 0)
            with self.assertRaisesRegex(ValueError, "already consumed"):
                self.authorize(
                    path,
                    event_id="inspect-002",
                    cycle_id="cycle-001",
                    now="2026-07-13T12:00:01Z",
                )
            with self.assertRaisesRegex(ValueError, "no persisted status-observed"):
                self.authorize(
                    path,
                    event_id="inspect-003",
                    cycle_id="cycle-002",
                    now="2026-07-13T12:09:59Z",
                )
            event = {
                "schema_version": "1",
                "event_id": "observed-001",
                "event_type": "status-observed",
                "task_id": "SPEC-101",
                "occurred_at": "2026-07-13T12:00:01Z",
                "run_id": "run-SPEC-101-impl-w01",
                "attempt_id": "attempt-SPEC-101-impl-w01-a01",
                "provider": "codex",
                "worker_id": "codex-thread:thread-1",
                "payload": {"authorization_event_id": "inspect-001"},
            }
            with (Path(directory) / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")
            allowed = self.authorize(
                path,
                event_id="inspect-004",
                cycle_id="cycle-003",
                now="2026-07-13T12:10:00Z",
            )
            self.assertEqual(allowed["authorization"]["payload"]["reason"], "scheduled")

    def test_heartbeat_cannot_claim_post_create_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.make_runtime(Path(directory))
            with self.assertRaisesRegex(ValueError, "scheduled or lease-risk"):
                self.authorize(
                    path,
                    event_id="inspect-001",
                    cycle_id="heartbeat-001",
                    now=NOW,
                    reason="post-create",
                    source="heartbeat",
                )

    def test_missing_event_log_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, runtime = self.make_runtime(Path(directory))
            runtime["event_log_file"] = ""
            path.write_text(json.dumps(runtime), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires event_log_file"):
                self.authorize(
                    path,
                    event_id="inspect-001",
                    cycle_id="cycle-001",
                    now=NOW,
                    reason="post-create",
                )

    def test_model_free_planner_sleeps_until_next_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, runtime = self.make_runtime(Path(directory))
            self.authorize(
                path,
                event_id="inspect-001",
                cycle_id="cycle-001",
                now=NOW,
                reason="post-create",
            )
            event = {
                "event_type": "status-observed",
                "run_id": "run-SPEC-101-impl-w01",
                "occurred_at": "2026-07-13T12:00:01Z",
                "payload": {"authorization_event_id": "inspect-001"},
            }
            with (Path(directory) / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")
            events = self.planner.load_events(Path(directory) / "events.jsonl")
            now = self.planner.parse_time(NOW)
            early = self.planner.plan_monitor_tick(
                runtime, events, now=now + timedelta(minutes=5)
            )
            due = self.planner.plan_monitor_tick(
                runtime, events, now=now + timedelta(minutes=10)
            )
            self.assertEqual(early["action"], "sleep")
            self.assertEqual(due["action"], "inspect")

    def test_planner_never_reauthorizes_an_unreconciled_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, runtime = self.make_runtime(Path(directory))
            self.authorize(
                path,
                event_id="inspect-001",
                cycle_id="cycle-001",
                now=NOW,
                reason="post-create",
            )
            events = self.planner.load_events(Path(directory) / "events.jsonl")
            result = self.planner.plan_monitor_tick(
                runtime, events, now=self.planner.parse_time(NOW) + timedelta(minutes=30)
            )
            self.assertEqual(result["action"], "reconcile-pending-inspection")
            self.assertEqual(result["authorization_event_id"], "inspect-001")
            self.assertFalse(result["resume_allowed"])

    def test_completion_closes_idle_completed_worker_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = self.make_runtime(root)
            self.authorize(
                path,
                event_id="inspect-001",
                cycle_id="cycle-001",
                now=NOW,
                reason="post-create",
            )
            result = self.completer.complete_inspection(
                path,
                authorization_event_id="inspect-001",
                event_id="observed-001",
                probe_status="idle",
                latest_turn_status="completed",
                terminal_outcome="succeeded",
                event_cursor="cursor-2",
                occurred_at="2026-07-13T12:00:01Z",
                event_schema=self.event_schema,
                write=True,
            )
            self.assertEqual(result["outcome"], "terminal-succeeded")
            self.assertEqual(
                result["required_host_action"],
                "collect-once-then-pause-heartbeat",
            )
            runtime = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(runtime["runs"][0]["status"], "succeeded")
            events = self.planner.load_events(root / "events.jsonl")
            self.assertEqual(events[-1]["payload"]["authorization_event_id"], "inspect-001")
            with self.assertRaisesRegex(ValueError, "already consumed"):
                self.completer.complete_inspection(
                    path,
                    authorization_event_id="inspect-001",
                    event_id="observed-002",
                    probe_status="succeeded",
                    latest_turn_status=None,
                    terminal_outcome=None,
                    event_cursor=None,
                    occurred_at="2026-07-13T12:00:02Z",
                    event_schema=self.event_schema,
                    write=True,
                )

    def test_model_free_planner_rejects_missing_event_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, runtime = self.make_runtime(Path(directory))
            runtime["event_log_file"] = ""
            with self.assertRaisesRegex(ValueError, "requires event_log_file"):
                self.planner.event_path(path, runtime)

    def test_terminal_collection_event_stops_repeated_collection(self) -> None:
        _, runtime = worker_bundle()
        run = runtime["runs"][0]
        run["status"] = "succeeded"
        run["finished_at"] = NOW
        now = self.planner.parse_time(NOW) + timedelta(minutes=10)
        self.assertEqual(self.planner.plan_monitor_tick(runtime, [], now=now)["action"], "collect-terminal")
        event = {"event_type": "terminal-collected", "run_id": run["run_id"], "occurred_at": NOW}
        result = self.planner.plan_monitor_tick(runtime, [event], now=now)
        self.assertEqual(result["action"], "stop")
        self.assertEqual(result["reason"], "terminal-already-collected")


if __name__ == "__main__":
    unittest.main()

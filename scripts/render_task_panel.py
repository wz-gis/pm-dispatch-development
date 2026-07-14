#!/usr/bin/env python3
"""Render the deterministic five-column PM task panel."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_pm_dispatch import load_structured_file  # noqa: E402


STATUS_LABELS = {
    "NEW": "方案待定",
    "TRIAGED": "待确认",
    "CONTRACT": "待确认",
    "READY_FOR_IMPL": "待实施",
    "IN_IMPL": "进行中",
    "READY_FOR_INTEGRATION": "待实施",
    "IN_INTEGRATION": "进行中",
    "READY_FOR_CLOSURE": "待验收",
    "VERIFIED": "已验证",
    "L0_VERIFIED_MOCK": "可选补验",
    "L1_VERIFIED_MOCK": "可选补验",
    "L2_VERIFIED_MOCK": "可选补验",
    "L3_VERIFIED_MOCK": "可选补验",
    "L4_VERIFIED_MOCK": "可选补验",
    "PARTIAL_VERIFIED": "可选补验",
    "ENV_BLOCKED": "环境阻塞",
    "CONTRACT_BLOCKED": "契约阻塞",
    "THREAD_BLOCKED": "Worker阻塞",
    "PM_BLOCKED": "PM阻塞",
    "CLOSED": "已关闭",
}

STATUS_GROUP = {
    "IN_IMPL": 0,
    "IN_INTEGRATION": 0,
    "ENV_BLOCKED": 1,
    "CONTRACT_BLOCKED": 1,
    "THREAD_BLOCKED": 1,
    "PM_BLOCKED": 1,
    "TRIAGED": 2,
    "CONTRACT": 2,
    "READY_FOR_IMPL": 2,
    "READY_FOR_INTEGRATION": 2,
    "READY_FOR_CLOSURE": 2,
    "NEW": 2,
    "PARTIAL_VERIFIED": 3,
    "L0_VERIFIED_MOCK": 3,
    "L1_VERIFIED_MOCK": 3,
    "L2_VERIFIED_MOCK": 3,
    "L3_VERIFIED_MOCK": 3,
    "L4_VERIFIED_MOCK": 3,
    "VERIFIED": 4,
    "CLOSED": 5,
}

FALLBACK_PROGRESS = {
    "NEW": "尚未开始",
    "TRIAGED": "已完成任务分诊",
    "CONTRACT": "公共契约确认中",
    "READY_FOR_IMPL": "已具备实施条件",
    "IN_IMPL": "实施中",
    "READY_FOR_INTEGRATION": "已具备联调条件",
    "IN_INTEGRATION": "联调中",
    "READY_FOR_CLOSURE": "等待验收收口",
    "VERIFIED": "验收证据已通过",
    "PARTIAL_VERIFIED": "部分证据已通过",
    "ENV_BLOCKED": "存在环境阻塞",
    "CONTRACT_BLOCKED": "存在契约阻塞",
    "THREAD_BLOCKED": "Worker 执行阻塞",
    "PM_BLOCKED": "等待 PM 决策",
    "CLOSED": "已关闭",
}
for mock_status in (
    "L0_VERIFIED_MOCK",
    "L1_VERIFIED_MOCK",
    "L2_VERIFIED_MOCK",
    "L3_VERIFIED_MOCK",
    "L4_VERIFIED_MOCK",
):
    FALLBACK_PROGRESS[mock_status] = "Mock 证据已通过，真实链路待补验"

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def render_task_panel(
    items: list[tuple[dict[str, Any], dict[str, Any] | None]],
    include_closed: bool = False,
) -> str:
    visible = [item for item in items if include_closed or item[0].get("status") != "CLOSED"]
    visible.sort(key=lambda item: panel_sort_key(item[0]))
    lines = [
        "**当前任务面板**",
        "",
        "| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for task, evidence in visible:
        status = str(task.get("status") or "")
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(value)
                for value in (
                    STATUS_LABELS.get(status, status or "未知"),
                    f"{task.get('id', 'UNKNOWN')} {task.get('title', '未命名任务')}",
                    task.get("priority", ""),
                    current_progress(task, evidence),
                    task.get("lifecycle", {}).get("next_action") or "待明确",
                )
            )
            + " |"
        )
    return "\n".join(lines)


def panel_sort_key(task: dict[str, Any]) -> tuple[int, int, str]:
    status = str(task.get("status") or "")
    priority = str(task.get("priority") or "P3")
    return (
        STATUS_GROUP.get(status, 9),
        PRIORITY_RANK.get(priority, 9),
        str(task.get("id") or ""),
    )


def current_progress(task: dict[str, Any], evidence: dict[str, Any] | None) -> str:
    if evidence:
        levels = evidence.get("verification", {}).get("levels", {})
        for level in ("L4", "L3", "L2", "L1", "L0"):
            level_data = levels.get(level) or {}
            if level_data.get("status") in {"pass", "pass_mock", "fail", "blocked"}:
                summary = level_data.get("summary")
                if summary:
                    return str(summary)
    for blocker in task.get("blockers", []):
        if blocker.get("status") == "open" and blocker.get("description"):
            return str(blocker["description"])
    return FALLBACK_PROGRESS.get(str(task.get("status") or ""), "进展待更新")


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def load_panel_items(tasks_dir: Path) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    task_paths = sorted(tasks_dir.glob("*/task.yaml"))
    task_paths.extend(sorted(tasks_dir.glob("*/task.json")))
    items = []
    for task_path in task_paths:
        task = load_structured_file(task_path)
        evidence_name = task.get("verification", {}).get("evidence_file") or "evidence.yaml"
        evidence_path = task_path.parent / evidence_name
        evidence = load_structured_file(evidence_path) if evidence_path.exists() else None
        items.append((task, evidence))
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the current PM task panel.")
    parser.add_argument("--tasks-dir", required=True, help="Path to docs/tasks")
    parser.add_argument("--include-closed", action="store_true")
    args = parser.parse_args()
    print(
        render_task_panel(
            load_panel_items(Path(args.tasks_dir).resolve()),
            include_closed=args.include_closed,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

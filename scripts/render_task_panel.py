#!/usr/bin/env python3
"""Render compact deterministic views of the five-column PM task panel."""

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

BLOCKED_STATUSES = {
    "ENV_BLOCKED",
    "CONTRACT_BLOCKED",
    "THREAD_BLOCKED",
    "PM_BLOCKED",
}
MOCK_VERIFIED_STATUSES = {
    "L0_VERIFIED_MOCK",
    "L1_VERIFIED_MOCK",
    "L2_VERIFIED_MOCK",
    "L3_VERIFIED_MOCK",
    "L4_VERIFIED_MOCK",
}
TERMINAL_PANEL_STATUSES = {"VERIFIED", "CLOSED"} | MOCK_VERIFIED_STATUSES
PANEL_VIEWS = {"actionable", "blocked", "waiting-user", "verified", "all"}
HUMAN_BLOCKER_CAUSES = {
    "credential",
    "human-authorization",
    "irreversible-contract",
}
DEFAULT_LIMIT = 8
DEFAULT_MAX_CHARS = 4000
MAX_PROGRESS_CHARS = 180
MAX_NEXT_ACTION_CHARS = 180


def render_task_panel(
    items: list[tuple[dict[str, Any], dict[str, Any] | None]],
    include_closed: bool = False,
    *,
    view: str = "actionable",
    task_id: str | None = None,
    limit: int | None = DEFAULT_LIMIT,
    max_chars: int | None = DEFAULT_MAX_CHARS,
) -> str:
    if view not in PANEL_VIEWS:
        raise ValueError(f"unsupported panel view {view!r}")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    if max_chars is not None and max_chars < 512:
        raise ValueError("max_chars must be at least 512")
    if include_closed:
        view = "all"

    visible = [
        item
        for item in items
        if (
            item[0].get("id") == task_id
            if task_id
            else task_matches_view(item[0], view)
        )
    ]
    visible.sort(key=lambda item: panel_sort_key(item[0]))
    if view == "all":
        release_rollups: dict[str, list[str]] = {}
    else:
        visible, release_rollups = roll_up_verified_releases(visible, items, task_id)

    total_visible = len(visible)
    if limit is not None:
        visible = visible[:limit]
    lines = [
        "**当前任务面板**",
        "",
        "| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for task, evidence in visible:
        status = str(task.get("status") or "")
        progress = current_progress(task, evidence)
        release_ids = release_rollups.get(str(task.get("id") or ""), [])
        if release_ids:
            progress = f"发布 {', '.join(release_ids)} 已收口；{progress}"
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(value)
                for value in (
                    STATUS_LABELS.get(status, status or "未知"),
                    f"{task.get('id', 'UNKNOWN')} {task.get('title', '未命名任务')}",
                    task.get("priority", ""),
                    trim_text(progress, MAX_PROGRESS_CHARS),
                    trim_text(
                        task.get("lifecycle", {}).get("next_action") or "待明确",
                        MAX_NEXT_ACTION_CHARS,
                    ),
                )
            )
            + " |"
        )

    hidden_count = total_visible - len(visible)
    return enforce_output_budget(lines, hidden_count, max_chars)


def task_matches_view(task: dict[str, Any], view: str) -> bool:
    status = str(task.get("status") or "")
    if view == "all":
        return True
    if view == "blocked":
        return status in BLOCKED_STATUSES
    if view == "waiting-user":
        return waits_for_user(task)
    if view == "verified":
        return status in TERMINAL_PANEL_STATUSES
    return status not in TERMINAL_PANEL_STATUSES


def waits_for_user(task: dict[str, Any]) -> bool:
    if task.get("status") == "PM_BLOCKED":
        return True
    return any(
        blocker.get("status") == "open"
        and blocker.get("hard") is True
        and blocker.get("cause") in HUMAN_BLOCKER_CAUSES
        for blocker in task.get("blockers", [])
        if isinstance(blocker, dict)
    )


def roll_up_verified_releases(
    visible: list[tuple[dict[str, Any], dict[str, Any] | None]],
    all_items: list[tuple[dict[str, Any], dict[str, Any] | None]],
    task_id: str | None,
) -> tuple[
    list[tuple[dict[str, Any], dict[str, Any] | None]],
    dict[str, list[str]],
]:
    if task_id:
        return visible, {}
    visible_ids = {str(item[0].get("id") or "") for item in visible}
    rollups: dict[str, list[str]] = {}
    hidden_release_ids: set[str] = set()
    for task, _ in all_items:
        release_id = str(task.get("id") or "")
        if task.get("type") != "release" or task.get("status") not in TERMINAL_PANEL_STATUSES:
            continue
        parents = [
            str(dependency.get("task_id") or "")
            for dependency in task.get("dependencies", {}).get("requires", [])
            if isinstance(dependency, dict)
            and str(dependency.get("task_id") or "") in visible_ids
        ]
        if not parents:
            continue
        hidden_release_ids.add(release_id)
        for parent_id in parents:
            rollups.setdefault(parent_id, []).append(release_id)
    for release_ids in rollups.values():
        release_ids.sort()
    return [item for item in visible if item[0].get("id") not in hidden_release_ids], rollups


def trim_text(value: Any, max_chars: int) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def enforce_output_budget(
    lines: list[str], hidden_count: int, max_chars: int | None
) -> str:
    footer = "| 省略 | 更多任务 |  |  | 使用 `--view all` 或 `--task TASK-ID` 查看 |"
    while True:
        candidate = list(lines)
        omitted = hidden_count
        if omitted:
            candidate.append(footer.replace("更多任务", f"另有 {omitted} 项"))
        rendered = "\n".join(candidate)
        if max_chars is None or len(rendered) <= max_chars:
            return rendered
        if len(lines) <= 4:
            raise ValueError("max_chars is too small for the panel header")
        lines.pop()
        hidden_count += 1


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
    parser.add_argument("--view", choices=sorted(PANEL_VIEWS), default="actionable")
    parser.add_argument("--task", dest="task_id", help="Render one TASK-ID")
    parser.add_argument("--limit", type=int, help=f"Maximum rows; default {DEFAULT_LIMIT}")
    parser.add_argument(
        "--max-chars",
        type=int,
        help=f"Maximum output characters; default {DEFAULT_MAX_CHARS}",
    )
    parser.add_argument("--include-closed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    limit = args.limit
    max_chars = args.max_chars
    if limit is None:
        limit = None if args.view == "all" or args.task_id else DEFAULT_LIMIT
    if max_chars is None:
        max_chars = None if args.view == "all" else DEFAULT_MAX_CHARS
    print(
        render_task_panel(
            load_panel_items(Path(args.tasks_dir).resolve()),
            include_closed=args.include_closed,
            view=args.view,
            task_id=args.task_id,
            limit=limit,
            max_chars=max_chars,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

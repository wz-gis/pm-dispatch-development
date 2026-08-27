#!/usr/bin/env python3
"""Measure deterministic PM context surfaces without estimating model tokens."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_task_panel import load_panel_items, render_task_panel  # noqa: E402
from validate_pm_dispatch import load_structured_file  # noqa: E402


def file_metrics(path: Path, root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    try:
        relative = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        relative = str(path.resolve())
    return {
        "path": relative,
        "bytes": len(raw),
        "chars": len(text),
        "lines": text.count("\n") + (0 if not text or text.endswith("\n") else 1),
    }


def collect_context_baseline(
    tasks_dir: Path,
    *,
    board_path: Path | None = None,
    top: int = 10,
    generated_at: str | None = None,
) -> dict[str, Any]:
    tasks_dir = tasks_dir.resolve()
    project_root = tasks_dir.parent.parent
    task_paths = sorted(tasks_dir.glob("*/task.yaml"))
    task_paths.extend(sorted(tasks_dir.glob("*/task.json")))
    evidence_paths: set[Path] = set()
    prompt_paths: list[Path] = []
    schema_versions: dict[str, int] = {}
    for task_path in task_paths:
        task = load_structured_file(task_path)
        version = str(task.get("schema_version") or "unknown")
        schema_versions[version] = schema_versions.get(version, 0) + 1
        evidence_name = task.get("verification", {}).get("evidence_file") or "evidence.yaml"
        evidence_path = Path(evidence_name)
        if not evidence_path.is_absolute():
            evidence_path = task_path.parent / evidence_path
        if evidence_path.exists():
            evidence_paths.add(evidence_path.resolve())
        prompt_dir = task_path.parent / "prompts"
        if prompt_dir.is_dir():
            prompt_paths.extend(
                path
                for path in sorted(prompt_dir.iterdir())
                if path.is_file() and path.suffix.lower() in {".md", ".txt", ".yaml", ".json"}
            )

    surfaces = [file_metrics(path, project_root) for path in task_paths]
    surfaces.extend(file_metrics(path, project_root) for path in sorted(evidence_paths))
    surfaces.extend(file_metrics(path, project_root) for path in prompt_paths)
    board_metrics = None
    if board_path and board_path.exists():
        board_metrics = file_metrics(board_path.resolve(), project_root)
        surfaces.append(board_metrics)

    items = load_panel_items(tasks_dir)
    actionable = render_task_panel(items)
    full = render_task_panel(items, view="all", limit=None, max_chars=None)
    largest = sorted(surfaces, key=lambda item: (-item["chars"], item["path"]))[:top]
    return {
        "schema_version": "1",
        "generated_at": generated_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "tasks_dir": str(tasks_dir),
        "task_count": len(task_paths),
        "task_schema_versions": dict(sorted(schema_versions.items())),
        "evidence_file_count": len(evidence_paths),
        "prompt_file_count": len(prompt_paths),
        "board": board_metrics,
        "panels": {
            "actionable": {
                "chars": len(actionable),
                "lines": actionable.count("\n") + 1,
            },
            "all": {"chars": len(full), "lines": full.count("\n") + 1},
        },
        "totals": {
            "bytes": sum(item["bytes"] for item in surfaces),
            "chars": sum(item["chars"] for item in surfaces),
            "lines": sum(item["lines"] for item in surfaces),
        },
        "largest_surfaces": largest,
        "note": "字符和字节是确定性基线；未使用模型相关 Token 估算。",
    }


def render_markdown(report: dict[str, Any]) -> str:
    board_chars = report.get("board", {}).get("chars") if report.get("board") else 0
    lines = [
        "# PM 上下文基线",
        "",
        f"- Task：{report['task_count']}",
        f"- Evidence 文件：{report['evidence_file_count']}",
        f"- Prompt 文件：{report['prompt_file_count']}",
        f"- 看板字符：{board_chars}",
        f"- 默认 actionable 面板字符：{report['panels']['actionable']['chars']}",
        f"- 全量面板字符：{report['panels']['all']['chars']}",
        f"- 总字符：{report['totals']['chars']}",
        "",
        "## 最大上下文表面",
        "",
        "| 文件 | 字符 | 行数 |",
        "| --- | ---: | ---: |",
    ]
    for item in report["largest_surfaces"]:
        lines.append(f"| {item['path']} | {item['chars']} | {item['lines']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure PM context surfaces.")
    parser.add_argument("--tasks-dir", required=True)
    parser.add_argument("--board")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output")
    parser.add_argument("--now")
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be at least 1")

    report = collect_context_baseline(
        Path(args.tasks_dir),
        board_path=Path(args.board) if args.board else None,
        top=args.top,
        generated_at=args.now,
    )
    rendered = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

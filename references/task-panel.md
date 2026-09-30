# Task Panel

Use five columns: Status, Task, Priority, Current Progress, Next Action.

| Status | Task | Priority | Current Progress | Next Action |
| --- | --- | --- | --- | --- |
| In progress | BUG-001 Fix pagination | P1 | Focused regression tests passed | Collect live API evidence |

The built-in renderer currently emits these Chinese labels; this is its existing locale, not a Schema requirement:

| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |
| --- | --- | --- | --- | --- |

- Task displays only `<id> <title>`, without duplicate priority/area/`display_name`.
- Current Progress contains verified facts. Next Action contains one action or decision.
- For a pending user decision, show the proposal's current state and the exact decision needed in Next Action. Use existing Task/decision records; do not add an unrecognized status enum or force a hard Blocker for display. Include a short pending project-decision note for PM migration, which has no delivery Task of its own. Read-only panel requests display pending decisions without resubmitting their input cards.
- Order active and blocked work first, then pending work, then optional items; sort P0-P3 within groups.
- Keep Owner, Worker, Run, Lease, and Adapter out of the main panel. Add runtime detail only on request or for an abnormal state.
- Do not repeat the table as prose or cards.
- Default `actionable`: at most 8 rows / 4,000 characters; verified/closed work is omitted.
- Successful releases roll up under a visible parent; show separately when active, failed, drifted, or explicitly queried.

Agent-written explanations follow the user's language. Translate presentation labels when needed, not IDs, enum values, facts, or evidence levels.

Run from the Skill directory, replacing the generic project path:

```bash
PROJECT=/path/to/project
python3 scripts/render_task_panel.py --tasks-dir "$PROJECT/docs/tasks"
python3 scripts/render_task_panel.py --tasks-dir "$PROJECT/docs/tasks" --view blocked
python3 scripts/render_task_panel.py --tasks-dir "$PROJECT/docs/tasks" --view waiting-user
python3 scripts/render_task_panel.py --tasks-dir "$PROJECT/docs/tasks" --view verified
python3 scripts/render_task_panel.py --tasks-dir "$PROJECT/docs/tasks" --task SPEC-002
python3 scripts/render_task_panel.py --tasks-dir "$PROJECT/docs/tasks" --view all
```

Views: `actionable`, `blocked`, `waiting-user`, `verified`, `all`. Override budgets with `--limit` and `--max-chars`. Script behavior and snapshot tests define sorting, rollups, and limits. Panel text is private unless reviewed; use `measure_context_baseline.py --public` for anonymous counts.

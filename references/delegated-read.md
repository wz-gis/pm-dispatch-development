# One-Shot Read-Only Delegation

## Scope

Use for panel summaries, prioritization, or read-only diagnosis that changes no code, PM records, or external state. This is not a delivery strategy: do not create a delivery Task, Run, Attempt, Lease, visible Worker, or Heartbeat. Implementation, repair, and acceptance use the normal workflow.

## Procedure

1. Render once: `render_task_panel.py --tasks-dir docs/tasks --view actionable --output /tmp/pm-dispatch/task-panel.md`. The coordinator reads only returned path, SHA, and character count.
2. Invoke the user's selected installed read-only agent once. Send the question, snapshot path/SHA, and output contract; do not first load the full panel or repeat agent discovery.
3. Limit output to 2,000 characters with `summary`, `priorities`, `blockers`, and `next_action`. Do not reproduce the panel.
4. Reuse the snapshot while its SHA is unchanged. Exit this mode before any write or project verification.

A panel snapshot may contain private task text. Keep it local; it is not the public aggregate report.

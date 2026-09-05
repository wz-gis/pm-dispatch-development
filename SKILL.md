---
name: pm-dispatch-development
description: Coordinate bug fixes and feature delivery with task boards, recoverable Workers, evidence-based gates, and bounded monitoring.
---

# PM Dispatch Development

Task/Evidence are authoritative; Workers recoverable. Gate updates need validated Evidence. Use the user's language; preserve keys/IDs.

## Fast Execution

1. Use the lowest sufficient model/effort allowed by the selected Adapter.
2. Without new evidence, do not expand exploration or repeat checks.
3. Implement once evidence is sufficient.
4. Verify correctness-critical paths and necessary regressions.
5. Do not expand scope for hypothetical future risks.
6. Stop after key checks pass unless new evidence appears.

Proceed with reversible work; stop only for hard Blockers. Except: high risk, security, data consistency.

## Load Only What You Need

- Boards: `render_task_panel.py --view actionable`; layout in `references/task-panel.md`.
- Records/Validator issues: `references/core-contract.md` and relevant Schema.
- Uncertainty/recovery/Blockers: `references/autonomy.md`.
- Examples: `references/task-examples.md`; prompts: `references/prompts.md`.
- Gemini/DeepSeek execution ("Gemini执行"/"DeepSeek执行"): `references/delegated-subagent.md`.
- Read-only: `references/delegated-read.md`; no Task/Run/Heartbeat.
- Dispatch: run Resolver/Adapter, validate Packet; no raw JSON by default. Codex: `references/adapters/codex.md`; others: `references/adapters/generic.md`.
- Token issues: `references/context-budget.md`; terminal reporting: `references/closure.md`.
- Skill edits: tests, consistency checks, `quick_validate.py`. Never inject README into Workers.

Machine contracts: Task v4 / Runtime v1 / Evidence v2; Task v3 is read/migrate only.

## Naming And Strategy

Display: `BUG-001 P1 API Fix pagination`; execution IDs: `BUG-001-impl-w01`, `run-...`, and `attempt-...-a01`. Prefixes: BUG, SPEC, ONBOARD, RELEASE, ENV, CHORE.

- `direct`: low-risk work in this conversation.
- `single-worker`: one task-sticky Worker reused across Gates.
- `batch-worker`: one Worker for 2-4 related tasks in the same project/Gate.
- `full-dispatch`: serial high-risk, cross-project delivery.

Choose the lightest verifiable strategy; escalate owner/repository/resource conflicts.

## Workflow

1. **Inspect**
   - Read panels/Packets, then referenced sources. Full reads need a protected trigger. Check Git before edits.

2. **Define**
   - Record type, priority, area, strategy, effort, capabilities, user path/runtime, L0-L4 evidence, checks, stop conditions.
   - Freeze/fingerprint scope, visible contracts, safety constraints, and acceptance before dispatch. Methods, files, commands, and ordinary test failures do not change it.

3. **Check Safety**
   - Validate before batch/parallel dispatch. Dependency, lock, concurrency, Attempt, or Lease errors block only the affected action.
   - Ordinary failure stays in the same Worker/Attempt: record, repair, verify once.
   - Use the task's canonical `manage_recovery_ledger.py`: `record` the first failure, `authorize` before retries. Limits: 2 same-method failures, 3 failed paths. An open breaker blocks execution, not inspection; resets need changed-state evidence.

4. **Dispatch**
   - Resolve `resolution`; Task does not accept model IDs. Codex omits `model` and uses the dispatch host default, not a temporary parent override; profiles map effort only.
   - This conversation is the sole PM Coordinator. Activate its Heartbeat before Worker creation; never target a Worker or create a second monitor task.
   - Codex v13: `manage_dispatch_transaction.py begin` allows 120 seconds to provision. `dispatch_preflight.py` validates Packet/Coordinator budget; saturation blocks only new Workers.
   - Explicit SPEC/BUG dispatch uses `create_thread` for a visible Worker (`direct`: none; batch: one). Complete the transaction with ID/Lease; on failure stop Heartbeat, then roll back.
   - With `dispatch.delegation`, only the visible Worker invokes the selected external agent.
   - Authorize the post-create zero-wait snapshot with `authorize_status_inspect.py`. Positive waits need `authorize_terminal_wait.py`: at most one 30-second wait per Run, never re-armed.
   - Every 10 minutes, this Heartbeat runs `plan_monitor_tick.py`: authorize one zero-wait snapshot for `inspect`, then persist `reconcile_worker_liveness.py` once. `sleep`/unchanged stops. No loops or positive waits.
   - Idle/interrupted is not completion. `diagnosis-required` gets one focused check; `awaiting-diagnosis` never auto-resumes. See `autonomy.md` for long commands.
   - On outage, mark liveness unknown and retain ownership. Reconcile the original Worker first; replace only after confirmed irrecoverability and a failed grace probe.
   - `single-worker` reuses `worker_id` across Gates; replacement requires a declared reason. Only safety-boundary or protected-freeze changes create a new Attempt.
   - Validate Packet sources/budgets. Reuse selects continuation: Packet SHA, Gate, remaining objective only; no full-scope fallback.

5. **Verify And Close**
   - Collect commit/file, command, API/SQL/browser, quality-check, and release artifacts. L0-L4 reference Artifact IDs.
   - Validator computes required/conditional checks and validates Evidence before Gate updates. Ordinary failures remain in the current Attempt.
   - Follow `references/closure.md`: report status, evidence, gaps, user action, commits, and one next step.

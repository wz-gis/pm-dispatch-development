# Worker Prompts

Use a stable prefix followed by task-specific data. Keep prefix wording/order unchanged within a project; translate it once if needed, not on every continuation.

## Worker

```markdown
[Stable execution contract]
Context: Use the validated Packet and named sources. Report source drift before editing.
Execution: Complete the objective within the frozen contract; choose implementation details from repository evidence.
Recovery: Stay in this Worker/Attempt and obey the canonical recovery ledger.
Progress: Send concise, monotonic milestones only for meaningful progress, risk boundaries, or terminal state.
Terminal: Validate the required records, then return status, identity, commit/files, Artifact IDs, blocker/user action, and next action once.

[Dynamic task suffix]
Task: SPEC-002 P1 WEB Add settings page
Identity: SPEC-002-impl-w01 / run-SPEC-002-impl-w01 / attempt-SPEC-002-impl-w01-a01
Resolution: provider=codex, model_id=null (host default), reasoning_profile=standard, provider_effort=inherit
Context Packet: <path> / <sha256>; validate before use
Delta: <one objective; initial Packet objective or continuation delta>
Sources: <exact source paths, or none>
Output: commit/files, Packet evidence gaps, hard blocker/user action, next action
```

Keep volatile IDs, paths, and progress in the dynamic suffix. Freeze design and build/validate the Packet before dispatch. A `single-worker` continuation sends only the current identity, Packet SHA, remaining objective, and evidence gaps. Pass a pending `--recovery-attempt` when recovering.

Full reads require a Packet trigger: `design-freeze-change`, `safety-boundary-change`, `contract-review`, `schema-migration`, `terminal-closure`, or `forensic-diagnosis`. Check character budgets, not line counts.

## Thin Wrapper Worker

Append only when `execution.delegation.mode=thin-wrapper-subagent` was explicitly authorized for the current request and host policy permits it. See `delegated-subagent.md`.

```markdown
[Stable thin-wrapper contract]
One visible Worker invokes the explicitly selected external definition from its checkout, then reviews the diff, runs focused verification, commits accepted work, and returns Evidence. The external call cannot own PM state, monitoring, Worker creation, or commits. Inspect artifacts before any repair; a differential repair requires concrete failing evidence.
```

Add only `Delegation: <agent> / initial=1 / repair=focused-failure-only` to the dynamic suffix. The external prompt references Packet path/SHA, one objective, exact sources, checks, and output fields, never PM history.

## Milestone

Send `progress_seq`, what materially changed, and the next action. The PM persists progress and renews the Lease; status-only renewal must not invent progress. Terminal delegation returns structured fields once.

## Codex Monitor

Codex visible Workers always use the coordinator Heartbeat because `create_thread` has no verified parent callback. Authorize one post-create zero-wait inspection, then persist it with `complete_status_inspect.py`; no later inspection is allowed while that result is missing. A positive terminal wait needs atomic authorization, at most 30 seconds once per Run. Preserve Attempt/locks on unreachability. External Adapters may use `event-lease` only with a real terminal event surface.

## Heartbeat

This template applies only to the visible-thread Adapter. Native internal agents use `adapters/codex-subagent.md` and do not create an Automation.

```markdown
Every 10m run plan_monitor_tick.py. Inspect: authorize one wait_threads(timeoutMs=0), then complete_status_inspect.py once. Otherwise perform required_host_action. Unmatched result: pause and report. No loops.
```

Bind to the current Coordinator: `target_thread_id=coordinator_thread_id`, never the Worker. Keep the substituted prompt within 240 characters. Zero waits consume inspection authorization, not the positive-wait budget. Same-cycle replay is forbidden; scheduled checks are at least 600 seconds apart. No positive Heartbeat wait.

`complete_status_inspect.py --write` reconciles once and records the authorization link. Only the first `diagnosis-required` result allows a focused diagnosis; `awaiting-diagnosis` does not send another "continue". For idle plus completed latest turn, pass an explicit terminal outcome from the delegation. After terminal collection append `terminal-collected`, perform the planner's required Automation pause, and persist Heartbeat status.

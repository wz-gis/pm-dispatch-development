# Worker Prompts

Use a stable prefix followed by task-specific data. Keep prefix wording/order unchanged within a project; translate it once if needed, not on every continuation.

## Worker

```markdown
[Stable execution contract]
Context: Read the validated Context Packet and its named source/Artifacts, not full Task/Evidence/Runtime, boards, or history by default.
Summaries: Prefer referenced Evidence Digest and project snapshot. Report semantic source drift to the PM before proceeding.
Recovery: Stay in this Worker/Attempt. Record the first failure in the task's canonical ledger; authorize before each retry, then record its outcome. At most 2 same-method failures and 3 failed paths per Gate/fingerprint. An open breaker allows inspection only; resets require changed-state evidence. See autonomy.md on failure.
Milestones: Send 1-2 sentences after the decision, core edit, focused verification, irreversible boundary, and terminal state.
Lease: Include progress_seq in each milestone; persist final progress before terminal delegation. Never create a parallel replacement Worker.
Terminal delegation: status, run/attempt, commit/files, verification Artifact IDs, hard blocker/user action, next action.

[Dynamic task suffix]
Task: SPEC-002 P1 WEB Add settings page
Identity: SPEC-002-impl-w01 / run-SPEC-002-impl-w01 / attempt-SPEC-002-impl-w01-a01
Resolution: provider=codex, model_id=null (host default), reasoning_profile=standard, provider_effort=inherit
Context Packet: <path> / <sha256>; validate before use
Delta: <one objective; initial Packet objective or continuation delta>
Sources: <exact source paths, or none>
Output: commit/files, Packet evidence gaps, hard blocker/user action, next action
```

Do not put IDs, timestamps, paths, Run/Attempt, or progress in the stable prefix. Freeze design and build/validate the Packet before dispatch. A `single-worker` continuation reuses the Worker and sends only Packet SHA, Run/Gate, delta, and evidence gaps. Preflight selects continuation automatically; its objective is explicit remaining work or `lifecycle.next_action`, never the full scope as fallback. Pass a pending `--recovery-attempt` when recovering.

Full reads require a Packet trigger: `design-freeze-change`, `safety-boundary-change`, `contract-review`, `schema-migration`, `terminal-closure`, or `forensic-diagnosis`. Check character budgets, not line counts.

## Thin Wrapper Worker

Append only for `execution.delegation.mode=thin-wrapper-subagent`; details in `delegated-subagent.md`.

```markdown
[Stable thin-wrapper contract]
Role: One visible Worker wraps one initial external implementation; no duplicate discovery or parallel coding.
Invoke: Validate Packet, send milestone, discover installed definitions, then invoke execution.delegation.agent from this Worker's $PWD.
Boundary: The sub-agent edits authorized sources and runs initial key tests. No PM-state edits, agent creation, monitoring, or Git commits.
Collect: Inspect changed paths/diff, run Packet-focused verification, commit accepted work, and return Artifacts by terminal delegation.
Recovery: Pre-execution launch failure may retry the same logical call. After partial/timeout, inspect Artifacts first; one delta repair requires concrete verification failure.
Stop: Passed focused verification with no new evidence means stop.
```

Add only `Delegation: <agent> / initial=1 / repair=focused-failure-only` to the dynamic suffix. The external prompt references Packet path/SHA, one objective, exact sources, checks, and output fields, never PM history.

## Milestone

Send `progress_seq`, what just finished, and the next action. The PM persists progress and renews the Lease; status-only renewal must not invent progress. Terminal delegation returns structured fields once.

## Event-Lease Watchdog

Authorize one post-create zero-wait inspection. A positive terminal wait needs atomic authorization, at most 30 seconds once per Run; end the turn after timeout. Later Heartbeats use the tick planner and a unique cycle ID. Preserve Attempt/locks on unreachability, then probe once after the grace period; recover only after confirmed irrecoverability.

## Heartbeat

```markdown
Every 10m run plan_monitor_tick.py here. Sleep: stop. Inspect: authorize one wait_threads(timeoutMs=0); read status, Lease, latest milestone. Reconcile changes; offline=unknown, retain ownership. No loops/new monitor.
```

Bind to the current Coordinator: `target_thread_id=coordinator_thread_id`, never the Worker. Keep the substituted prompt within 240 characters. Zero waits consume inspection authorization, not the positive-wait budget. Same-cycle replay is forbidden; scheduled checks are at least 600 seconds apart. No positive Heartbeat wait.

Reconcile once with `reconcile_worker_liveness.py --write`. Only the first `diagnosis-required` result allows a focused diagnosis; `awaiting-diagnosis` does not send another "continue". Idle/interrupted never means successful completion. After verified terminal collection, append `terminal-collected` and stop the host Automation; a planner `stop` is a decision, not the host action itself.

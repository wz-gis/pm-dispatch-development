# Autonomy And Recovery

Load only for uncertainty, failed recovery, or Blocker decisions.

## Default Action

- Make reversible, local, verifiable choices and record material assumptions in Evidence.
- Ask only when local discovery cannot answer, alternatives materially change the outcome, and a wrong choice is costly or irreversible.
- Warnings do not stop implementation. Validator errors block only their affected dispatch, Gate, or closure action.

## User Decisions And Visibility

Request only a decision actually needed and not already authorized. Prepare the proposed change, evidence, and tradeoffs first. For Codex, use `request_user_input_async` when available for user decisions or workflow approval; otherwise use another supported user-input UI only in modes and cases where that tool permits it. Do not assume a Plan-only tool is available in Default mode. Tool execution permissions still use the host's native approval mechanism, not a substitute decision card.

Ask in the project PM conversation. Include the task ID, the concrete decision, why it matters, a short recommendation, and the reviewable artifact path. Offer a few meaningful options when useful. The host controls whether this appears as an inline card or dialog; do not claim a modal was shown without a successful tool result. Never ask for secrets in a card.

Persist pending decisions in the existing task decisions record and `lifecycle.next_action`: what is awaiting the user, the proposal/evidence link, and when it was asked. Use a hard Blocker only if its established criteria apply. For a project-wide migration, use the coordination/handoff record and show a pending-decision note with the task panel; do not create a synthetic Bug solely to track the question.

An asynchronous question stays pending until an actual reply arrives. Pause only work dependent on that decision and continue independent authorized work. A preselected option, silence, elapsed time, or an unrelated 'continue' is not approval. Heartbeats must not submit duplicate questions while the same decision is pending. On reply, record the answer and its reference, update the next action, and resume the approved work.

If no suitable input UI is callable or the call fails, keep the pending record, tell the user that the confirmation card is unavailable, and ask one clear question in the main response. Never silently replace a failed approval UI with assumed consent. Ordinary progress updates do not require confirmation cards.

## Same-Worker Recovery

A first command, build, test, or tool failure is not a Blocker and does not create an Attempt. The current Worker may retry the same method once, try up to two materially different alternatives, and run focused verification. Local implementation, file layout, and test commands may change within that Attempt.

Persist actual failures in `<task-dir>/context/recovery-ledger.json`, never a temporary Packet directory. Keep the same Gate/failure fingerprint for the same unresolved problem across turns, Workers, and output paths. Method names identify materially different approaches, not retry numbers. Existing Workers missing this ledger must reconcile/import legacy history before continuation; initialize an empty ledger only after establishing that no recovery history exists. Inspection must not create a fresh ledger. Once a working environment/toolchain is evidenced, reuse it; a failed metadata check does not justify rediscovering Java, containers, or the whole repository.

1. `manage_recovery_ledger.py <task> record --gate <gate> --failure-class <class> --failure-fingerprint <sha256> --attempt-key <key> --method <method> --result failed --next-action <delta>` records the initial failure. Optional `--checkpoint-ref <file>` captures its hash for later reset proof.
2. Before retrying, `authorize --gate <gate> --attempt-key <new-key> --method <method>` atomically reserves one recovery. Build/validate a continuation Packet with `--recovery-attempt <new-key>`. After that attempt, `record` the same key/fingerprint/method as `failed` or `recovered`, with Artifact refs. Do not batch-record failures after repeated execution.
3. At most two failures of one method and three failed paths are allowed. An open breaker forbids execution even in another Gate. `--purpose inspect` allows diagnosis/record repair but cannot authorize a Worker prompt. A pending reservation after interruption must be reconciled against the original process/Artifacts; never execute it a second time just because a response was lost.
4. `reset` requires `--reason`, existing `--artifact-ref` evidence, and a changed actual Task design or previously hashed checkpoint. Reason wording alone never resets a budget. History and reset proofs remain recorded. Import a legacy ledger explicitly with `import --import-ledger <path>` only into an empty canonical ledger; reconcile multiple nonempty histories once, never select the shortest one.

Create a new Attempt only for:
- A credential, permission, destructive-data, release, or other safety-boundary change.
- A new protected `design_freeze` fingerprint for scope, visible contracts, safety constraints, or acceptance.

For disconnection, probe the original Worker and retry once after the grace period. Only an expired Lease plus a Provider-confirmed irrecoverable Worker crosses the ownership boundary: expire the old Attempt, release locks, and recover from its last Artifact/progress. A single wait timeout neither creates an Attempt nor marks the Task Blocked.

## Interrupted Or Stalled Work

After an authorized status snapshot, persist `reconcile_worker_liveness.py ... --write` once. An idle/interrupted Provider state is neither successful delegation nor proof that its subprocesses stopped: the Run/Attempt become queued, retain identity/locks, and request one reconciliation. A completed turn still needs its terminal outcome and Evidence checked. Resume only the remaining objective in the same Worker after checking the last milestone, pending command, and recovery reservation.

With no new milestone for 30 minutes, a reachable Worker returns `diagnosis-required` once per progress checkpoint. Inspect one relevant command/result and record a concrete failure or wait condition. Subsequent `awaiting-diagnosis` results retain liveness checks but do not send repeated "continue", launch a replacement, or redo discovery. New persisted progress clears the attention state; do not fabricate progress merely to renew a Lease.

A verified long build/test can supply `--command-id <session> --command-deadline <ISO-time>`. The fixed deadline defers the no-progress diagnosis; it cannot slide or change command identity without a new milestone. At expiry, diagnose once rather than kill/restart automatically. Monitor/network gaps remain `unknown`, not failed recoveries. For confirmed terminal outcomes, collect once, append `terminal-collected`, then stop the host Automation and persist Heartbeat status; the planner returns `stop` on replay.

## Hard Blockers

Only credentials/2FA/CAPTCHA, missing authorization for an irreversible external action, high-cost protected-contract ambiguity, real dependency/lock conflicts, external unavailability after two distinct recovery paths, or an exhausted recovery budget may block. Record `hard`, `cause`, `recovery_attempts`, and one `next_unblock_action`.

## Risk-Scaled Verification

| Changed surface | Evidence |
| --- | --- |
| Local change | Focused tests and diff review |
| Shared behavior | Relevant regression suite |
| Cross-system path | Integration evidence |
| Production or irreversible path | Runtime, rollback, and user-path evidence |

Collect only what the current Gate requires. Do not repeat passed, unaffected checks.

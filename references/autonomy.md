# Autonomy And Recovery

Load only for uncertainty, failed recovery, or Blocker decisions.

## Default Action

- Make reversible, local, verifiable choices and record material assumptions in Evidence.
- Ask only when local discovery cannot answer, alternatives materially change the outcome, and a wrong choice is costly or irreversible.
- Warnings do not stop implementation. Validator errors block only their affected dispatch, Gate, or closure action.

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

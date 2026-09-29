# Codex Adapter

Read when `codex-routing.md` selects visible Codex threads, not native internal agents. Check actual host tool availability and creation authorization first. Resolver chooses effort; omit `model` so the Worker uses the dispatch host default.

## Dispatch Transaction

1. Freeze the protected contract and resolve the Codex Adapter.
2. Run dispatch from the established project PM and bind the target Run's Heartbeat there. Reuse that PM across tasks; invocation elsewhere does not transfer ownership. A visible Worker has no verified parent-wakeup callback, so use `direct` when periodic monitoring is disabled. Never target the Worker or create a monitor task.
3. Begin provisioning with `manage_dispatch_transaction.py`, then run `dispatch_preflight.py`. Preflight validates the Packet, Heartbeat, locks, recovery state, and coordinator budget.
   Coordinator usage is advisory. PM migration requires a prepared handoff and user approval as described in `../project-coordinator.md`.
4. Create the visible task with `create_thread`, then complete the transaction with its real thread ID and Lease. A queued `clientThreadId` is not a Worker ID. On confirmed creation failure, pause the Heartbeat before rollback.
5. Authorize one post-create zero-wait snapshot and persist its result with `complete_status_inspect.py`. A short terminal wait is optional and must be authorized by `authorize_terminal_wait.py`; the machine policy permits one call of at most 30 seconds per Run.

Provisioning timeout, operation arguments, event ordering, and idempotency are defined by `codex.adapter.json` and enforced by the transaction, authorization, and validation scripts.

## Monitoring

Every 10-minute Heartbeat runs `plan_monitor_tick.py` once and performs only its returned action:

- `sleep`: make no Provider call.
- `inspect`: authorize one `wait_threads(timeoutMs=0)` snapshot, then consume that authorization with `complete_status_inspect.py --write`.
- `reconcile-pending-inspection`: recover the missing result once or pause the Heartbeat.
- terminal or expired provisioning: collect or roll back once, perform `required_host_action`, and pause the Automation.

Do not loop, use a positive wait from Heartbeat, or issue another snapshot while an authorization is unmatched. Idle/interrupted is not success. For idle plus a completed latest turn, use the delegation's explicit terminal outcome; if it is unavailable, pause for repair instead of guessing.

On monitor or network failure, keep the Attempt, Lease ownership, and locks while liveness is unknown. Inspect the original Worker after recovery. Replace it only after Provider-confirmed irrecoverability and the required grace probe.

## Continue And Close

Reuse a `single-worker` Worker across Gates and send only current identity, Packet SHA, remaining objective, and evidence gaps. Ordinary failures stay in the same Worker/Attempt and follow the recovery ledger.

Collect a confirmed terminal outcome once. Validate Task/Runtime/Evidence before a Gate change, append `terminal-collected`, pause the host Automation, persist Heartbeat status, and report closure. Script output is a decision; host actions still must be executed.

These scripts authorize and audit native calls; they do not proxy MCP tools or keep a disconnected host running.

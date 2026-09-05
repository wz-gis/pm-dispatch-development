# Codex Adapter

Read only when creating or recovering a visible Codex Worker. Use Resolver effort; do not choose its model in the Skill.

1. Resolve the route, freeze scope/contracts/safety/acceptance, and copy the fingerprint into the Run.
2. Record the current PM conversation as the sole `coordinator_thread_id` with `coordinator_epoch`. Use `automation_update(kind=heartbeat)` to activate its Heartbeat for the intended Run, never for the Worker.
3. Run `manage_dispatch_transaction.py begin` for a Run without a Worker ID. Provisioning defaults to 120 seconds; locks cannot outlive it.
4. Run `dispatch_preflight.py`. It validates Heartbeat, Packet, and Coordinator budget. At 160K last-input tokens or 150 recorded model steps, stop creating new Workers; existing monitoring/closure remain allowed.
5. For explicitly dispatched visible work, use `create_thread` with `worker_label`, omitting `model`. Once a real thread ID is available, run transaction `complete` to bind ID/Lease. On confirmed failure, stop Heartbeat and `rollback --heartbeat-stopped`. A queued `clientThreadId` is not a real thread ID; reconcile uncertain creation before retrying.
6. Run `authorize_status_inspect.py --reason post-create --cycle-id <turn> --write`, then use its `native_arguments` for one zero-wait snapshot. Reference the authorization ID in the observation event; do not bypass authorization.
7. If a short wait is needed, run `authorize_terminal_wait.py ... --timeout-ms 30000 --write`, call the returned arguments once, and record `terminal-wait-finished`. Each Run gets at most one positive wait. End the turn if unfinished.
8. Every Heartbeat runs `plan_monitor_tick.py` once. `sleep`: stop. `inspect`: authorize a scheduled snapshot using the Heartbeat-run cycle ID, then persist `reconcile_worker_liveness.py --write` once. No positive waits or loops. `diagnosis-required` gets one focused check; `awaiting-diagnosis` never resends a continuation. Verified long commands use a fixed deadline, not a sliding timeout.
9. Append events for mutations, observations, and terminal collection. Validate with `--codex-session-dir ~/.codex/sessions` to audit native waits that bypass authorization.
10. Recover ordinary failures in the same Worker/Attempt using canonical `record`/`authorize` recovery entries. Idle/interrupted status (including `status.type`) requires reconciliation, not success or replacement. Preserve ownership during an outage; inspect the original Worker and its grace probe before replacement.
11. Reuse `worker_id` across `single-worker` Gates. Preflight selects continuation; send only Packet SHA, Gate, and remaining objective. An open breaker permits `--purpose inspect`, not execution. Replacements require a declared trigger.
12. Collect a confirmed terminal outcome once, append `terminal-collected`, stop the host Automation, and persist Heartbeat status. The planner's `stop` result does not itself call the host tool.

These scripts authorize and audit calls; they do not hide or proxy the host's native MCP tools. Host scheduling, connectivity, and explicit task-creation permissions still apply.

# Native Codex Subagent Adapter

Use after `codex-routing.md` selects `codex-subagent`. This is internal delegation, not a separate visible desktop task and not the external-agent Skill. No external CLI or model is launched.

Do not set `dispatch.delegation`: that optional contract is for an explicitly requested external wrapper, not native Codex agents.

## Dispatch And Reuse

Keep the project PM, task identity, frozen Packet, Task/Runtime/Evidence, dependencies, resource locks, recovery ledger, and Gate checks unchanged. Set provider policy and allowed providers to `codex-subagent`, with `heartbeat_required=false`; resolve to `worker_type=codex-subagent` and `monitor_mode=milestone`. Do not create an Automation for this path.

Use the existing provisioning transaction and Preflight. Build native calls with `adapter_protocol.py --host-tools` and the binding selected in `codex-routing.md`. The bundled spawn signature uses the compact Packet as `message`; alternate fields come from live declarations. Omit model/effort overrides and full-history forking by default. Record the returned real agent ID, then complete provisioning and acquire its Lease. The transaction key deduplicates local dispatch only; native spawn has no idempotency parameter. After an ambiguous spawn failure, reconcile the host result before retrying.

Assign a bounded objective and disjoint write scope. Verify the host's workspace semantics; review and integrate returned changes when it uses a forked workspace. Reuse the same live agent through the verified continuation binding (`send_input`, `followup_task`, or `send_message`). Bind native argument/result fields once instead of treating one spelling as mandatory. Do not interrupt unless redirection is intended; a separate `interrupt_agent` is not an ordinary follow-up or a close operation.

## Completion And Recovery

Prefer host terminal notifications. Persist meaningful received milestones and the terminal result once in the existing event log; do not fabricate heartbeat renewals or progress. Native `wait_agent` is a blocking terminal wait with a 10,000 ms minimum, NOT a zero-wait status inspection. There is no native inspect/rebind operation in this Adapter.

Waiting is optional: without a wait tool, rely on verified parent completion notifications. When waiting is available and the result blocks the next critical-path step, use `authorize_terminal_wait.py --host-tools <binding-file> --write` before at most one 10-30 second wait per Run. Invoke the returned native arguments. Record `terminal-wait-finished` with authorization ID and outcome even for timeout/call-error. After timeout, do other non-overlapping work or yield to the host's documented completion notification; do not loop or reset the budget in a new turn. This path never runs the visible-thread snapshot/Heartbeat procedure.

Decode a `wait_agent` result or equivalent host notification using `adapter_protocol.py --result ... --worker-id ...`. A timeout, interrupted agent, missing agent, or disconnect is not success. Without a completion event, liveness remains unknown; retain ownership and record one recovery action. This Adapter does not guarantee survival across host restart or PM replacement. Do not release locks or spawn a replacement merely because a Lease expired.

The decoder's `status=unknown` is an observation, not a Runtime Run state: keep the last nonterminal Run state and reconcile the Lease's liveness. Never write `unknown` into `run.status`.

The native `completed` event means the agent returned, not that acceptance passed. Review its explicit task outcome, actual diff and evidence; persist failed/blocked outcomes accurately and validate Gates before success. If `close_agent` exists, collect evidence before closing; it may terminate descendants and is not a success signal. If it is absent, finish the bounded task through the normal host lifecycle and do not claim explicit resource release. Interruption neither proves closure nor permits releasing locks. Keep a live Worker only while useful for the same task. No arbitrary Run-count rotation.

Adapters describe native envelopes but do not proxy tools. Use the exact discovered namespace and schema; script authorization cannot hide or intercept a direct native call.

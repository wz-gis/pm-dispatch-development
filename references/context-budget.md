# Context Budget

## Read Boundaries

- A direct task reads only its relevant Task/Evidence, Git delta, and machine summaries.
- Do not load unrelated tasks, archived boards/releases, or the full dispatch board.
- Cross-task full reads need a concrete dependency conflict, safety change, failed recovery, or terminal audit. Explain the trigger before reading.
- Use existing Digest, snapshot, Packet, or actionable panel instead of rereading its full source. Do not reload unchanged full files.
- Continuations receive the latest milestone, Packet SHA, and delta.
- Preflight automatically selects `continuation` when a Worker already exists. Use `--objective` for remaining work, otherwise `lifecycle.next_action`; missing continuation objectives fail instead of replaying accepted scope. The recovery ledger stays in the task directory across all temporary bundles.

## PM Records

Use the current Schema/Validator or a valid same-version example, not remembered fields. Generate a valid skeleton, fill Evidence once, then validate the task. Fix reported fields only; a record-format error does not justify new builds, browser runs, or full-history reads.

## Script First

Extract board, Git, dependencies, runtime, Gate, and usage facts with scripts. Models consume compact results, not a file-by-file repository tour.

## Long Conversations

Separate existing host conversation history from newly injected context; the Skill cannot clear host history.

`check_coordinator_budget.py` provides advisory usage only. At 96K last-input tokens it recommends reducing newly injected context; it does not block dispatch or require another Coordinator. Lifetime `token_count` records are telemetry, not current context pressure. Missing counters are `unknown`. Legacy rollover fields and CLI options remain readable for compatibility but have no blocking effect.

Keep one project PM across tasks and Gates. First reduce context with compact Packets and supported in-place compaction. When migration is justified, prepare the handoff and obtain user approval before creating a replacement PM; follow `project-coordinator.md`. `coordinator_epoch` versions that approved transfer, not each bug or Run. Historical `handoff-required` reports are diagnostics, not migration permission or execution blockers.

## Monitoring And Delegation

Heartbeat runs `plan_monitor_tick.py`; `sleep` makes no Provider status call. `inspect` uses `authorize_status_inspect.py` and a unique cycle ID, at least 600 seconds apart for scheduled checks. The planner itself uses no model, but a host-scheduled Heartbeat may still consume model tokens.

Persist one liveness reconciliation after the snapshot. `diagnosis-required` permits one focused investigation; `awaiting-diagnosis` does not resend a prompt. A verified long command uses a fixed completion deadline. Terminal collection is deduplicated by its event; unchanged checks never rebuild Packets or reread recovery history. See `autonomy.md` only when a diagnosis is needed.

When the current request explicitly selects a separate read-only agent and host policy permits it, use `delegated-read.md`. For publication, run `measure_context_baseline.py --public`: it exports aggregate counts only. Normal baseline output, Packets, Evidence, and session logs are not anonymized.

Report cached input separately in token comparisons. Character counts, prompt caps, requested waiting time, elapsed time, and billed tokens are different measurements. Do not claim cross-task savings without a controlled baseline.

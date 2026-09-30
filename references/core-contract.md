# PM Dispatch Core Contract

## Contents

- Naming
- State invariants
- Dispatch and runtime invariants
- Lean context contract
- Dependencies and locks
- Evidence contract
- Validation

## Naming

Use a stable machine ID and a derived human-readable label.

```text
task_id:      BUG-001
display_name: BUG-001 P1 API Fix pagination
worker_name:  BUG-001-impl-w01
worker_label: BUG-001 P1 API Fix pagination [impl w01]
run_id:       run-BUG-001-impl-w01
attempt_id:   attempt-BUG-001-impl-w01-a01
```

Task IDs use `<TYPE>-<three digits>`. Supported types are `BUG`, `SPEC`, `ONBOARD`, `RELEASE`, `ENV`, and `CHORE`. The ID prefix must match `task.yaml.type`.

Derive `display_name` exactly as:

```text
<id> <priority> <area joined by /> <title>
```

## State Invariants

Keep lifecycle, verification, blocker, and closure as separate tracks, but validate them together.

| Task status | Lifecycle phase | Verification | Closure |
| --- | --- | --- | --- |
| `NEW` | `intake` | `NONE` or `PENDING` | `open` |
| `TRIAGED` | `triage` | `PENDING` | `open` |
| `CONTRACT` | `contract` | `PENDING` | `open` |
| `READY_FOR_IMPL`, `IN_IMPL` | `implementation` | `PENDING` | `open` |
| `READY_FOR_INTEGRATION`, `IN_INTEGRATION` | `integration` | `PENDING` | `open` |
| `READY_FOR_CLOSURE` | `closure` | verified-like | `ready` |
| `VERIFIED`, `L*_VERIFIED_MOCK` | `closure` | matching verified status | `ready` or `closed` |
| `PARTIAL_VERIFIED` | `verification` or `closure` | `PARTIAL` | `open` or `ready` |
| blocked states | current phase | `BLOCKED` | `open` |
| `CLOSED` | `archive` | verified-like | `closed` |

`READY_FOR_CLOSURE`, verified-like, partial, blocked, and closed tasks require `evidence.yaml`. `CLOSED` also requires `accepted_by`, `accepted_at`, and `closed_at`.

## Dispatch And Runtime Invariants

- The established project PM is the sole active coordinator across tasks. Dispatch runs in that conversation; invoking the Skill elsewhere does not create or transfer the PM role. Before visible-thread Worker creation, bind or update `automation_update(kind=heartbeat)` on that PM, with target equal to `coordinator_thread_id`. Native internal agents use parent completion notifications without an Automation; see `adapters/codex-routing.md`. See `project-coordinator.md` for user-approved migration.
- A visible Codex Worker uses `create_thread`; an internal Codex Worker uses `spawn_agent`. Select from actual host capabilities and authorization through `adapters/codex-routing.md`, not the model name. The project PM owns coordination and acceptance; `direct` creates neither kind of Worker, and `batch-worker` uses one Worker per Batch.
- A Worker thread never owns the Heartbeat, and no second monitor thread/task is created. The Heartbeat in the current coordinator conversation observes the Worker thread recorded by the target Run.
- Optional `dispatch.delegation` is valid only after a current explicit request and when host policy permits it. `thin-wrapper-subagent` keeps one pinned Codex Worker and one initial external call; that Worker retains checkout, PM-state, monitoring, verification, commit, and closure ownership. One differential repair is allowed only after focused verification fails.
- `direct` uses local provider policy and has no runs, reasoning profile, resolution, heartbeat, lease, or resource lock.
- Worker strategies require `worker_required: true`, `reasoning_profile`, `fallback_policy`, `resolution`, and a positive `max_parallel_workers`.
- `reasoning_profile` contains only portable effort intent: `fast`, `standard`, `deep`, or `critical`.
- Task dispatch never accepts a user-provided model ID. Codex Adapters omit `model` and record `model_id: null`: visible threads use the host default, while native internal agents inherit the parent model and effort. Do not assume these inheritance rules are interchangeable.
- `resolution` records the selected Provider, Adapter version, declared `model_id` when applicable, provider-specific reasoning value, Worker type, monitor mode, capabilities, and evidence kinds.
- Worker dispatch requires `design_freeze.status=frozen`. Canonicalize `scope`, `constraints`, `acceptance`, and `change_policy` to calculate its SHA-256 fingerprint, then copy that fingerprint into the active Run.
- The protected freeze covers scope, user-visible contracts, safety constraints, and acceptance. Implementation methods, file layout, commands, test selection, and ordinary repair do not change it.
- Only a safety-boundary change or protected freeze fingerprint change creates a new Attempt. Ordinary recoverable failures stay in the same Worker and Attempt for one same-method retry, up to two materially different recovery paths, and one focused re-verification.
- `single-worker` is task-sticky: implementation, integration, verification, ordinary repair, and Evidence supplementation reuse the same Provider Worker across Runs and Gates. A different Worker requires a structured replacement reason allowed by `worker_reuse.replacement_triggers`; a Gate transition alone is never a replacement reason.
- Run count never forces replacement. `max_runs_per_worker` is optional legacy metadata, ignored by the reuse gate and omitted from new examples/migration defaults. `context-saturated` requires observed inability to continue after context reduction, not a counter threshold.
- `strict` requires a pinned Provider. `compatible` may use declared fallback Providers, but never silently drops required capabilities or reasoning support.
- A pinned Provider is tried first; in `compatible` mode a different Provider is valid only when listed in `allowed_providers`.
- Every active Run copies actual Provider, model, and reasoning fields from the current `resolution`; terminal historical Runs preserve the Provider, model, and reasoning values that actually executed them. Request fields never masquerade as runtime facts.
- `IN_IMPL` and `IN_INTEGRATION` worker tasks require at least one Run.
- Every Run has one or more Attempts; Attempt IDs are unique within the Run.
- `provisioning` is the only active state without `worker_id` or Lease. It has one provisioning Attempt, a pending transaction, and a deadline no more than five minutes after start. An executing `queued`/`running` Run has exactly one active Attempt, a real `worker_id`, and an unexpired Lease.
- Lease `holder` equals `run_id`; acquisition precedes expiry.
- Terminal Runs cannot contain active Attempts.
- Active Run count cannot exceed `max_parallel_workers`.
- A visible Codex Worker has no verified parent-wakeup callback. Codex Adapter v15 therefore requires `heartbeat_required=true` and `monitor_mode=heartbeat`; disabling periodic monitoring means choosing `direct`, not an untracked background Run.
- An incremental check reads only Worker status, Lease metadata, and the latest persisted milestone (`progress_seq`, time, summary, optional event cursor). Reconcile once with `reconcile_worker_liveness.py --write`; unchanged live work renews the same Attempt without full Task/Evidence/history reads. After 30 minutes without progress, persist one `diagnosis-required` observation, then return `awaiting-diagnosis` until real progress. A verified running command may defer diagnosis until its fixed deadline.
- A full reconciliation is triggered only by a new milestone, terminal state, safety-boundary change, or protected design-freeze change. It then reads the relevant Task/Evidence and runtime facts needed to update the Gate and single next action.
- Incremental monitoring uses `scan_scope: incremental`, `lightweight: true`, the fixed read set, `context_policy: coordinator`, and `interval_minutes: 10`. `plan_monitor_tick.py` is the model-free decision core. `sleep` performs no Provider call; `inspect` requires a unique `status-inspect-authorized` event, one call per cycle, and 600-second scheduled debounce. It never loops or runs in a second monitor task.
- `event-lease` is available only to Adapters with a real Provider event surface, Lease renewal, and terminal wakeup. Both Codex paths permit one authorized wait of at most 30 seconds per Run, never reset by a later turn. Native agents use `milestone` completion notifications, not a Lease watchdog, and require a 10-second minimum wait.
- Visible-thread dispatch order is fixed: activate the coordinator Heartbeat, begin a 120-second provisioning transaction, pass Preflight, create the Worker, complete the transaction with Worker ID/Lease, authorize one post-create snapshot, then optionally perform one wait of at most 30 seconds. Create failure first stops Heartbeat and then rolls back the transaction and locks. Native agents use the same provisioning/Preflight/Lease sequence without Heartbeat or snapshots. A timeout never re-arms the wait.
- Before the native positive wait, `authorize_terminal_wait.py` atomically appends `terminal-wait-authorized`; a second authorization, a timeout above 30 seconds, or a Heartbeat source fails. Append `terminal-wait-finished` after the call. Runtime validation checks the budget and event order; optional Codex session audit reports positive native `wait_threads` calls without matching authorization.
- Before every native zero-wait snapshot, `authorize_status_inspect.py` atomically consumes its cycle ID. The result must immediately pass through `complete_status_inspect.py`, which reconciles Runtime and appends the matching `status-observed`. An unmatched authorization blocks all later snapshots; the planner returns one recovery action instead of polling again. Scheduled checks less than 600 seconds apart fail. Optional Codex session audit reports native zero-wait calls without matching authorization.
- Preflight writes advisory `coordinator-budget.json`; usage thresholds never block Worker creation or require a new Coordinator. Keep the original PM conversation and its Heartbeat. Only an explicit user request to migrate the Coordinator permits rebinding and an epoch increment. See `context-budget.md` for legacy report handling.
- Monitor/network/app unavailability sets `liveness_state: unknown` and `monitor_gap_started_at` without releasing the Attempt, Lease ownership, or locks. After connectivity returns, inspect the original Worker first. Only a Provider-confirmed irrecoverable identity followed by one grace probe crosses the ownership boundary: expire that Attempt, release its locks, preserve its last Artifact/cursor, then recover. A missed check or expired timestamp alone is neither Blocked nor permission to duplicate-dispatch.
- Persist each milestone in the Lease as monotonic `progress_seq`, `last_progress_at`, `last_progress_summary`, and optional Provider `event_cursor`. Status-only renewal updates `heartbeat_at` but does not invent progress.
- Idle/interrupted Provider states do not alone prove success or that subprocesses stopped. An idle Worker with a completed latest turn requires one explicit terminal classification from its delegation; otherwise inspection completion fails and monitoring pauses for repair. Terminal reconciliation is idempotent; a matching `terminal-collected` event makes the planner require Automation pause. Expired provisioning likewise requires rollback followed by Automation pause.
- Workers report concise monotonic milestones for meaningful progress, risk-boundary changes, and terminal state. Terminal delegation reports status, Run/Attempt, commit/files, verification Artifact IDs, hard blocker/user action, and next action.
- Event/ milestone monitoring has no periodic full Task, Evidence, or history inspection and requires no `dispatch.heartbeat` metadata.
- A Codex Heartbeat runs in the established project PM conversation. Its target equals `coordinator_thread_id`, differs from every Worker ID, and monitors the declared `target_run_id`; `monitor_thread_id` is invalid. All live task bindings in one project must agree on the PM owner.
- The Heartbeat uses the fixed incremental read set and immediately reconciles triggered changes. Prompt limits come from Runtime Schema; referenced Task/Evidence are not loaded on unchanged checks.
- An active Run monitored by Heartbeat requires `heartbeat.status=active`; no active Run permits only `paused` or `stopped`.
- Every active incremental Heartbeat interval is exactly 10 minutes. Blocked work without an active Run pauses monitoring; an explicitly active recovery Run keeps the same 10-minute check.
- Automation schedule, Task heartbeat metadata, and `max_checks` coverage must be updated together. A heartbeat check reconciles terminal Runs before doing any further work.
- `batch-worker` requires a `BATCH-*` ID, a human-readable batch `display_name`, and 2-4 distinct task IDs including the current task. Derive the visible Worker label from the batch display name.

## Lean Context Contract

`Context Packet v1` is a deterministic derived cache, not an authoritative record. Each source declares `digest_kind`: Task/Evidence/ledger use file hashes, Runtime uses a semantic projection, and derived summaries use normalized identities. Packet identity excludes generation time, source placement, Lease expiry, and Provider cursor. Project-snapshot source identity also excludes its absolute root. Lease renewal or relocation does not create a new semantic Packet; milestone, state, design, or evidence changes still invalidate it.

Before dispatch, derive `current-evidence.json` (current Evidence state) and `project-snapshot.json` (Git/files/focused sources). `dispatch_preflight.py` may place these caches outside the project, but recovery history is always `<task-dir>/context/recovery-ledger.json`. New output directories never reset it. Legacy temporary ledgers require explicit import/reconciliation; never overwrite a nonempty canonical ledger. Validate source and structural integrity before execution.

Recovery counts by Gate and failure fingerprint: `record` the initial failure, atomically `authorize` before a retry, and `record` its outcome using the reserved key. Change method after two same-method failures. Three failed paths open the breaker. Executable Packets and active-Run validation reject open breakers or unreserved recovery; `--purpose inspect` cannot authorize Worker prompts. Reset requires evidence of a changed Task design or recorded checkpoint, not a new prompt, method label, or reason wording. Preserve attempt/reset history; ordinary recovery never creates a Runtime Attempt.

Initial Workers receive a stable execution prefix, Packet path/SHA, objective, and exact source paths. Reusing a Worker makes Preflight default to continuation: new Packet SHA, Gate, and delta only. Use an explicit remaining objective or `lifecycle.next_action`; an empty continuation objective fails instead of falling back to accepted scope. Do not inject full Task/Evidence/Runtime/boards/history by default. Full reads require one recorded trigger: `design-freeze-change`, `safety-boundary-change`, `contract-review`, `schema-migration`, `terminal-closure`, or `forensic-diagnosis`.

The Packet builder defaults to 8,000 characters; initial prompts to 6,000 and continuation prompts to 3,000. Complex Packets can explicitly increase to 16,000. Preflight uses a stricter shared 6,000-character default for its bundle artifacts. Character budgets are not token counts or fixed line limits. Example commands:

```bash
python3 scripts/build_context_packet.py docs/tasks/SPEC-002/task.yaml \
  --gate implementation --verification-command "python3 -m unittest"
python3 scripts/validate_context_packet.py \
  docs/tasks/SPEC-002/context/active-context.json \
  --prompt docs/tasks/SPEC-002/prompts/01-implementation.md

python3 scripts/dispatch_preflight.py docs/tasks/SPEC-002/task.yaml \
  --project-root . --gate implementation \
  --focus frontend/app/page.tsx \
  --verification-command "python3 -m unittest"
```

Semantic source drift, Packet hash mismatch, exceeded budgets, and unauthorized full reads stop Worker creation. Detailed commands, logs, SQL, DOM, and history stay in referenced Artifacts.

## Dependencies And Locks

Board dependencies must be present in the same `--tasks-dir` validation set. External dependencies require a status and `evidence_ref`. Dependency cycles are invalid.

Every active resource lock:

- has an expiry;
- points to an active Run in the same task;
- does not outlive an executing Run's Lease or a provisioning Run's deadline;
- obeys shared/exclusive conflict rules across the board.

Run global validation before parallel dispatch:

```bash
python3 scripts/validate_pm_dispatch.py --tasks-dir docs/tasks
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-001/task.yaml --automation-dir ~/.codex/automations
python3 scripts/reconcile_worker_liveness.py docs/tasks/BUG-001/task.yaml \
  --run-id run-BUG-001-impl-w01 --probe-status running --write
```

## Autonomy And Blockers

Every dispatch carries `autonomy_policy`: proceed by default, clarify only material irreversible ambiguity, block only on a hard blocker, and verify by risk. A first command, build, test, or tool failure is never a blocker.

Blocked states require an open `hard: true` blocker with a classified cause, recovery count, and one next unblock action. Credentials, human authorization, protected-contract ambiguity, real dependencies, and resource conflicts may block immediately. External unavailability or exhausted recovery requires at least two materially different recovery attempts. See `autonomy.md` only when recovery or blocking decisions are needed.

## Evidence Contract

Evidence is structured data, not a prose assertion. Task `quality_checks` declares a risk-scaled policy without changing Lifecycle. Each check has a stable ID, `required`/`conditional`/`optional` requirement, changed-surface triggers, and allowed Artifact kinds. Evidence records status, tool, summary, Artifact refs, skip reason, and check time. At Closure, Gate Policy computes triggered conditional checks, requires every actual required check to pass, rejects unresolved failed/blocked results, and validates every passing ref against a passing Artifact of an allowed kind. A skipped check is valid only when it is not required and includes a reason. Test, static-analysis, security, and review commands remain Provider/CI concerns; the core only validates their results.

Browser, API, SQL, screenshot, log, ID, upgrade, and release artifacts require:

```yaml
artifact_id: browser-001
kind: browser
source: codex-browser
subject: existing user opens pagination controls
result: pass
captured_at: 2026-07-13T12:00:00Z
evidence_ref: evidence/browser-001.json
```

Artifacts may record `pass`, `fail`, or `info`. Failed and informational artifacts remain valid history but cannot satisfy a terminal Gate. Command artifacts additionally require `command` and `exit_code`; passing commands require exit code zero. Passing API artifacts require `status_code`. Required L0-L4 `evidence_refs` must resolve to a passing Artifact ID.

## Adapter Protocol

Adapter protocol v2 declares `create`, `send`, `inspect`, `wait`, `rebind`, `collect`, and `cancel`. Operations define caller inputs, immutable fixed inputs, result paths, timeout, and idempotency; results normalize Provider status and may persist a continuation token, event cursor, or terminal delegation. Adapter schema v3 permits Provider-specific model routing, but the Codex Adapter omits `model` so child Workers use the dispatching host's configured default model.

Build an invocation envelope and decode the provider result through:

```bash
python3 scripts/adapter_protocol.py references/adapters/external-cli.adapter.json create \
  --idempotency-key create-SPEC-002-a01 \
  --inputs '{"title":"SPEC-002 Settings page","prompt":"implement and verify","reasoning_effort":"deliberate"}'
```

Task v4 keeps stable intent in `task.yaml`; Resolution, Heartbeat, locks, Run/Attempt/Lease, continuation state, and event cursors live in Runtime v1. Runtime events are append-only JSONL. Legacy embedded Task v3 remains readable, while migration validates Task v4, Runtime v1, and Evidence v2 before writing and preserves the original Task backup.

After each mutating Adapter operation or observed Worker transition, validate and append one event through `scripts/record_runtime_event.py`. Never rewrite prior event lines; duplicate IDs and time regressions fail closed.

## Validation

The validator supports the JSON Schema keywords used by the bundled schemas and fails if a future schema introduces an unsupported keyword. Run:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/resolve_pm_dispatch.py docs/tasks/BUG-001/task.yaml --write
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-001/task.yaml
```

The machine sources of truth are:

- `references/schemas/task.schema.json`
- `references/schemas/evidence.schema.json`
- `references/schemas/runtime.schema.json`
- `references/schemas/runtime-event.schema.json`
- `references/schemas/adapter.schema.json`
- `references/adapters/*.adapter.json`
- `scripts/resolve_pm_dispatch.py`
- `scripts/adapter_protocol.py`
- `scripts/record_runtime_event.py`
- `scripts/render_task_panel.py`
- `scripts/measure_context_baseline.py`
- `scripts/build_context_packet.py`
- `scripts/validate_context_packet.py`
- `scripts/validate_pm_dispatch.py`
- `scripts/validate_skill_consistency.py`

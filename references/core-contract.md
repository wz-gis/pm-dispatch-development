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
task_id:      BUG-041
display_name: BUG-041 P1 AA 最近诊断记录
worker_name:  BUG-041-impl-w01
worker_label: BUG-041 P1 AA 最近诊断记录 [impl w01]
run_id:       run-BUG-041-impl-w01
attempt_id:   attempt-BUG-041-impl-w01-a01
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

- `direct` uses local provider policy and has no runs, reasoning profile, resolution, heartbeat, lease, or resource lock.
- Worker strategies require `worker_required: true`, `reasoning_profile`, `fallback_policy`, `resolution`, and a positive `max_parallel_workers`.
- `reasoning_profile` contains only portable effort intent: `fast`, `standard`, `deep`, or `critical`.
- Task dispatch never accepts a user-provided model ID. A Provider Adapter may select a declared model when required, but the Codex Adapter omits `model` so a child Worker uses the dispatching host's configured default model; this records `model_id: null`. A temporary per-thread model override is not copied automatically.
- `resolution` records the selected Provider, Adapter version, declared `model_id` when applicable, provider-specific reasoning value, Worker type, monitor mode, capabilities, and evidence kinds.
- Worker dispatch requires `design_freeze.status=frozen`. Canonicalize `scope`, `constraints`, `acceptance`, and `change_policy` to calculate its SHA-256 fingerprint, then copy that fingerprint into the active Run.
- The protected freeze covers scope, user-visible contracts, safety constraints, and acceptance. Implementation methods, file layout, commands, test selection, and ordinary repair do not change it.
- Only a safety-boundary change or protected freeze fingerprint change creates a new Attempt. Ordinary recoverable failures stay in the same Worker and Attempt for one same-method retry, up to two materially different recovery paths, and one focused re-verification.
- `single-worker` is task-sticky: implementation, integration, verification, ordinary repair, and Evidence supplementation reuse the same Provider Worker across Runs and Gates. A different Worker requires a structured replacement reason allowed by `worker_reuse.replacement_triggers`; a Gate transition alone is never a replacement reason.
- `strict` requires a pinned Provider. `compatible` may use declared fallback Providers, but never silently drops required capabilities or reasoning support.
- A pinned Provider is tried first; in `compatible` mode a different Provider is valid only when listed in `allowed_providers`.
- Every active Run copies actual Provider, model, and reasoning fields from the current `resolution`; terminal historical Runs preserve the Provider, model, and reasoning values that actually executed them. Request fields never masquerade as runtime facts.
- `IN_IMPL` and `IN_INTEGRATION` worker tasks require at least one Run.
- Every Run has one or more Attempts; Attempt IDs are unique within the Run.
- An active Run has exactly one active Attempt, a real `worker_id`, and an unexpired Lease.
- Lease `holder` equals `run_id`; acquisition precedes expiry.
- Terminal Runs cannot contain active Attempts.
- Active Run count cannot exceed `max_parallel_workers`.
- `heartbeat_required` means periodic background monitoring is required. The Codex Resolver prefers `heartbeat`; the dispatch coordinator performs one incremental check every 10 minutes.
- An incremental check reads only Worker status, Lease metadata, and the latest persisted milestone (`progress_seq`, time, summary, optional event cursor). An unchanged live Worker renews the same Attempt without loading Task, Evidence, dependencies, locks, Gate history, or the full transcript.
- A full reconciliation is triggered only by a new milestone, terminal state, safety-boundary change, or protected design-freeze change. It then reads the relevant Task/Evidence and runtime facts needed to update the Gate and single next action.
- Incremental monitoring uses `scan_scope: incremental`, `lightweight: true`, the fixed three-item `read_set`, `context_policy: coordinator`, and `interval_minutes: 10`. It runs in the dispatch coordinator task and never creates a second monitor Worker or task.
- `event-lease` combines push milestones, Provider-native terminal waiting, and a Lease-expiry watchdog. The wait blocks until terminal activity or the current Lease deadline; it does not read Worker history.
- On a terminal event, collect terminal delegation. On a wait timeout, invoke the Adapter `inspect` operation once and read only Worker status plus Lease metadata. A live Worker renews the same Attempt and re-arms the wait.
- Monitor/network/app unavailability sets `liveness_state: unknown` and `monitor_gap_started_at` without releasing the Attempt, Lease ownership, or locks. After connectivity returns, inspect the original Worker first. Only a Provider-confirmed irrecoverable identity followed by one grace probe crosses the ownership boundary: expire that Attempt, release its locks, preserve its last Artifact/cursor, then recover. A missed check or expired timestamp alone is neither Blocked nor permission to duplicate-dispatch.
- Persist each milestone in the Lease as monotonic `progress_seq`, `last_progress_at`, `last_progress_summary`, and optional Provider `event_cursor`. Status-only renewal updates `heartbeat_at` but does not invent progress.
- Milestone Workers notify after root-cause/implementation decision, core edit, focused verification, irreversible boundary, and terminal state. Running messages are 1-2 sentences. Terminal delegation reports status, Run/Attempt, commit/files, verification Artifact IDs, hard blocker/user action, and next action.
- Event/ milestone monitoring has no periodic full Task, Evidence, or history inspection and requires no `dispatch.heartbeat` metadata.
- A Codex Heartbeat runs in the dispatch coordinator thread. Its Automation target equals `coordinator_thread_id`, differs from every Worker ID, and monitors the declared `target_run_id`; `monitor_thread_id` is invalid.
- The Heartbeat prompt requires the fixed incremental read set and immediate triggered reconciliation. The Task budget cannot exceed 240 characters; referenced Task/Evidence remain machine facts and are not loaded on unchanged checks.
- An active Run monitored by Heartbeat requires `heartbeat.status=active`; no active Run permits only `paused` or `stopped`.
- Every active incremental Heartbeat interval is exactly 10 minutes. Blocked work without an active Run pauses monitoring; an explicitly active recovery Run keeps the same 10-minute check.
- Automation schedule, Task heartbeat metadata, and `max_checks` coverage must be updated together. A heartbeat check reconciles terminal Runs before doing any further work.
- `batch-worker` requires a `BATCH-*` ID, a human-readable batch `display_name`, and 2-4 distinct task IDs including the current task. Derive the visible Worker label from the batch display name.

## Lean Context Contract

`Context Packet v1` 是 Task、Runtime 和 Evidence 的确定性派生缓存，不是新的事实源。分发前由 `build_context_packet.py` 生成，必须包含来源路径与 SHA-256、当前 Run/Attempt/Gate、设计指纹、目标、范围、已确认事实、当前失败/Blocker、依赖、活动锁、证据缺口和字符预算。`packet_sha256` 排除 `generated_at`，因此来源和语义不变时重复生成保持稳定。

Worker 首轮默认只接收稳定执行前缀、Context Packet 路径/SHA、差量目标和确切源码路径；同一 Worker 续跑只发送新 Packet SHA、Gate 和差量。禁止默认注入完整 Task、Evidence、Runtime、dispatch-board 或历史 Prompt。以下触发器之一必须写入 Packet，才允许全文读取：`design-freeze-change`、`safety-boundary-change`、`contract-review`、`schema-migration`、`terminal-closure`、`forensic-diagnosis`。

默认预算为 Packet 8000 字符、首轮 Prompt 6000 字符、续跑 Prompt 3000 字符。复杂任务可将 Packet 提高到 16000 字符，但必须在生成命令中显式覆盖；不得用固定行数替代字符预算。生成与校验命令：

```bash
python3 scripts/build_context_packet.py docs/tasks/SPEC-042/task.yaml \
  --gate implementation --verification-command "python3 -m unittest"
python3 scripts/validate_context_packet.py \
  docs/tasks/SPEC-042/context/active-context.json \
  --prompt docs/tasks/SPEC-042/prompts/01-implementation.md
```

来源 SHA 漂移、Packet 自身摘要漂移、超预算或未经授权的全文读取都必须在 Worker 创建前 fail closed。Context Packet 只保留当前 Gate 所需引用；详细命令、日志、SQL、DOM 和历史仍留在对应 Artifact。

## Dependencies And Locks

Board dependencies must be present in the same `--tasks-dir` validation set. External dependencies require a status and `evidence_ref`. Dependency cycles are invalid.

Every active resource lock:

- has an expiry;
- points to an active Run in the same task;
- does not outlive that Run's Lease;
- obeys shared/exclusive conflict rules across the board.

Run global validation before parallel dispatch:

```bash
python3 scripts/validate_pm_dispatch.py --tasks-dir docs/tasks
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml --automation-dir ~/.codex/automations
python3 scripts/reconcile_worker_liveness.py docs/tasks/BUG-041/task.yaml \
  --run-id run-BUG-041-impl-w01 --probe-status running --write
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
subject: existing user opens recent diagnostics
result: pass
captured_at: 2026-07-13T12:00:00Z
evidence_ref: evidence/browser-001.json
```

Artifacts may record `pass`, `fail`, or `info`. Failed and informational artifacts remain valid history but cannot satisfy a terminal Gate. Command artifacts additionally require `command` and `exit_code`; passing commands require exit code zero. Passing API artifacts require `status_code`. Required L0-L4 `evidence_refs` must resolve to a passing Artifact ID.

## Adapter Protocol

Adapter protocol v2 declares `create`, `send`, `inspect`, `wait`, `rebind`, `collect`, and `cancel`. Operations define target inputs, result paths, timeout, and idempotency; results normalize Provider status and may persist a continuation token, event cursor, or terminal delegation. Adapter schema v3 permits Provider-specific model routing, but the Codex Adapter omits `model` so child Workers use the dispatching host's configured default model.

Build an invocation envelope and decode the provider result through:

```bash
python3 scripts/adapter_protocol.py references/adapters/external-cli.adapter.json create \
  --idempotency-key create-SPEC-042-a01 \
  --inputs '{"title":"SPEC-042 页面","prompt":"implement and verify","reasoning_effort":"deliberate"}'
```

Task v4 keeps stable intent in `task.yaml`; Resolution, Heartbeat, locks, Run/Attempt/Lease, continuation state, and event cursors live in Runtime v1. Runtime events are append-only JSONL. Legacy embedded Task v3 remains readable, while migration validates Task v4, Runtime v1, and Evidence v2 before writing and preserves the original Task backup.

After each mutating Adapter operation or observed Worker transition, validate and append one event through `scripts/record_runtime_event.py`. Never rewrite prior event lines; duplicate IDs and time regressions fail closed.

## Validation

The validator supports the JSON Schema keywords used by the bundled schemas and fails if a future schema introduces an unsupported keyword. Run:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/resolve_pm_dispatch.py docs/tasks/BUG-041/task.yaml --write
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml
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

# PM Dispatch Development

A PM-oriented delivery skill for single-project work, multi-project integration, and new-project onboarding. It coordinates structured Tasks, Evidence, Run/Attempt/Lease recovery, dependency graphs, and resource locks.

## Highlights

- Machine IDs use `BUG-041` and `SPEC-042`.
- Human labels use `BUG-041 P1 AA Recent Diagnostics`.
- Workers have unique machine names and labels, such as `BUG-041-impl-w01` and `BUG-041 P1 AA Recent Diagnostics [impl w01]`.
- Closed, partial, blocked, and verified-like states require Evidence.
- Browser, API, and SQL evidence use structured Artifacts instead of free-form strings.
- Every 10 minutes, the dispatch coordinator reads only Worker status, Lease metadata, and the latest milestone. Triggered reconciliation loads complete relevant facts without creating a second monitor task.
- Monitor or network outages mark liveness unknown while preserving Attempt, Lease ownership, and locks; recovery reconciles the original Worker first.
- Recoverable failures stay in the same Worker/Attempt. Only safety-boundary or protected-design changes create a new Attempt.
- The validator checks the state matrix, hard Blockers, concurrency, Run/Attempt/Lease, dependency cycles, and resource locks.
- A compact quality-check contract lets Gate Policy validate test, static-analysis, security, and review Evidence without adding Lifecycle states.
- The core contract is platform-neutral; the Resolver selects an Adapter from portable capability and reasoning requests, while Codex child Workers use the dispatching host's configured default model.
- Adapter protocol v2 makes continuation, wait, rebind, terminal collection, idempotency, and status mapping machine-readable.
- Task v4 stores stable intent, Runtime v1 stores volatile execution state and event cursors, and Evidence uses Schema v2; embedded Task v3 remains migratable.

## Install

Place the directory at:

```text
~/.codex/skills/pm-dispatch-development
```

Invoke it with:

```text
Use $pm-dispatch-development to define this Task, dispatch a Worker, collect Evidence, and close the Gate.
```

## Naming

```text
task_id:      BUG-041
display_name: BUG-041 P1 AA Recent Diagnostics
worker_name:  BUG-041-impl-w01
worker_label: BUG-041 P1 AA Recent Diagnostics [impl w01]
run_id:       run-BUG-041-impl-w01
attempt_id:   attempt-BUG-041-impl-w01-a01
```

Supported prefixes are `BUG`, `SPEC`, `ONBOARD`, `RELEASE`, `ENV`, and `CHORE`.

## Dispatch Strategies

| Strategy | Use |
| --- | --- |
| `direct` | Handle a low-risk task in the current thread without Worker runtime state |
| `single-worker` | One task-sticky Worker implements and verifies across Runs and Gates |
| `batch-worker` | One Worker covers 2-4 similar Tasks with independent conclusions |
| `full-dispatch` | Cross-project, database, release, migration, or high-risk real-chain work |

## Reasoning Adapters

The core uses four portable `reasoning_profile` values and never accepts a user-provided model ID in Task. The Codex Adapter omits `model`, so child Workers use the dispatching host's configured default model; profiles only map Codex reasoning effort. Temporary per-thread model overrides are not copied automatically.

| Core profile | Model source | Codex effort |
| --- | --- | --- |
| `fast` | dispatch host default | inherit |
| `standard` | dispatch host default | inherit |
| `deep` | dispatch host default | `high` |
| `critical` | dispatch host default | `high` |

The machine contract is defined by [codex.adapter.json](references/adapters/codex.adapter.json). Other Providers may still declare their own model routing when needed.

```bash
python3 scripts/resolve_pm_dispatch.py docs/tasks/BUG-041/task.yaml --write
```

## Automatic Gates

The validator checks:

- Task ID, type, priority, Area, title, and `display_name` consistency.
- Lifecycle, Verification, Blocker, and Closure invariants.
- Required terminal Evidence and matching conclusions.
- Artifact structure, timestamps, results, and L0-L4 references.
- Real Worker IDs, unique Attempts, and valid Leases for active Runs.
- Ten-minute incremental coordinator Heartbeat, triggered full reconciliation, outage ownership protection, Worker reuse, and concurrency limits.
- Loaded board dependencies and dependency cycles.
- Active resource locks, active holder Runs, and Lease bounds.

```bash
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml --automation-dir ~/.codex/automations
python3 scripts/validate_pm_dispatch.py --tasks-dir docs/tasks
```

## Self-Test

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_skill_consistency.py
python3 -m py_compile scripts/*.py tests/*.py
for file in references/schemas/*.json references/adapters/*.adapter.json; do python3 -m json.tool "$file" >/dev/null; done
```

Dry-run legacy migration before explicitly writing files:

```bash
python3 scripts/migrate_pm_dispatch.py docs/tasks
python3 scripts/migrate_pm_dispatch.py docs/tasks --write
```

Write mode validates Task v4, Runtime v1, or Evidence v2 output. It backs up the original Task/Evidence and creates Runtime plus an empty event-log sidecar. The default panel shows only actionable work; other views are loaded on demand:

```bash
python3 scripts/render_task_panel.py --tasks-dir docs/tasks
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --view waiting-user
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --task SPEC-042
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --view all
```

Build and validate a lean Context Packet before dispatch. The deterministic baseline records characters, bytes, and lines without inventing model-token estimates:

```bash
python3 scripts/measure_context_baseline.py --tasks-dir docs/tasks \
  --board docs/dispatch-board.md --output /tmp/pm-context-baseline.json
python3 scripts/build_context_packet.py docs/tasks/SPEC-042/task.yaml \
  --gate implementation --verification-command "python3 -m unittest"
python3 scripts/validate_context_packet.py \
  docs/tasks/SPEC-042/context/active-context.json \
  --prompt docs/tasks/SPEC-042/prompts/01-implementation.md
```

## Sources Of Truth

- `SKILL.md`: execution order and progressive-disclosure routing.
- `references/core-contract.md`: platform-neutral invariants.
- `references/task-examples.md`: Task, Worker runtime, and Evidence structure examples.
- `references/prompts.md`: Worker and Heartbeat prompts.
- `references/autonomy.md`: uncertainty, recovery budgets, and hard Blocker decisions.
- `references/task-panel.md`: task-panel presentation contract.
- `references/closure.md`: terminal Gates and user-facing closure reports.
- `references/adapters/*.adapter.json`: machine-readable Provider policies.
- `references/adapters/*.md`: Provider instructions.
- `references/schemas/`: formal data structures.
- `scripts/validate_pm_dispatch.py`: Gate, dependency, and lock validation.
- `scripts/validate_skill_consistency.py`: cross-file monitoring, protocol, and Runtime consistency checks.
- `scripts/resolve_pm_dispatch.py`: capability, reasoning, and Provider fallback resolution.
- `scripts/adapter_protocol.py`: Worker operation envelopes and provider-result decoding.
- `scripts/reconcile_worker_liveness.py`: deterministic renewal, disconnect grace, Attempt expiry, and lock release.
- `scripts/record_runtime_event.py`: validates and appends immutable Runtime events while rejecting duplicate IDs and time regressions.
- `scripts/migrate_pm_dispatch.py`: conservative migration of embedded Tasks to Task v4/Runtime v1 and legacy Evidence to v2.
- `scripts/render_task_panel.py`: five-column views with budgets and verified RELEASE rollups.
- `scripts/measure_context_baseline.py`: deterministic board, Task, Evidence, Prompt, and panel surface metrics.
- `scripts/build_context_packet.py`: derives a compact Context Packet with source digests.
- `scripts/validate_context_packet.py`: validates Packet integrity, source drift, character budgets, and prompt full-read authorization.
- `tests/`: persistent Adapter, Resolver, migration, and Gate regression tests.

Schemas, Adapter JSON, and the validator are authoritative. The README does not redefine fields.

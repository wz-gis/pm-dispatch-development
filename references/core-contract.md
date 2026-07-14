# PM Dispatch Core Contract

## Contents

- Naming
- State invariants
- Dispatch and runtime invariants
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

- `direct` uses local provider policy and has no runs, model request, resolution, heartbeat, lease, or resource lock.
- Worker strategies require `worker_required: true`, `model_request`, `fallback_policy`, `resolution`, and a positive `max_parallel_workers`.
- `model_request` contains only portable intent: quality, `reasoning_profile`, latency, and cost.
- `resolution` records the selected Provider, Adapter version, model, provider-specific reasoning value, Worker type, monitor mode, capabilities, and evidence kinds.
- `strict` requires a pinned Provider. `compatible` may use declared fallback Providers, but never silently drops required capabilities or reasoning support.
- A pinned Provider is tried first; in `compatible` mode a different Provider is valid only when listed in `allowed_providers`.
- Every Run copies actual Provider/model/reasoning fields from `resolution`; request fields never masquerade as runtime facts.
- `IN_IMPL` and `IN_INTEGRATION` worker tasks require at least one Run.
- Every Run has one or more Attempts; Attempt IDs are unique within the Run.
- An active Run has exactly one active Attempt, a real `worker_id`, and an unexpired Lease.
- Lease `holder` equals `run_id`; acquisition precedes expiry.
- Terminal Runs cannot contain active Attempts.
- Active Run count cannot exceed `max_parallel_workers`.
- Heartbeat resolution requires structured heartbeat metadata. Compatible manual fallback must be explicit in both policy and resolution.
- `batch-worker` requires a `BATCH-*` ID, a human-readable batch `display_name`, and 2-4 distinct task IDs including the current task. Derive the visible Worker label from the batch display name.

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
```

## Evidence Contract

Evidence is structured data, not a prose assertion. Browser, API, SQL, screenshot, log, ID, upgrade, and release artifacts require:

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

Adapter protocol v1 declares Worker `transport` plus structured `create`, `inspect`, and `cancel` operations. Each operation defines its target, required inputs, timeout, Worker ID path, and status path. Adapter integrity validation also enforces unique model IDs and valid default/fallback model references. Individual models may support only the reasoning profiles they actually implement.

Build an invocation envelope and decode the provider result through:

```bash
python3 scripts/adapter_protocol.py references/adapters/external-cli.adapter.json create \
  --inputs '{"title":"SPEC-042 页面","prompt":"implement and verify"}'
```

Migration validates every v2 result before writing any input. `--write` uses an atomic replacement and preserves the original as `<name>.v1.bak`; unknown Providers and invalid migrated output stop before overwrite.

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
- `references/schemas/adapter.schema.json`
- `references/adapters/*.adapter.json`
- `scripts/resolve_pm_dispatch.py`
- `scripts/adapter_protocol.py`
- `scripts/render_task_panel.py`
- `scripts/validate_pm_dispatch.py`

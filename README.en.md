# PM Dispatch Development

A PM-oriented delivery skill for single-project work, multi-project integration, and new-project onboarding. It coordinates structured Tasks, Evidence, Run/Attempt/Lease recovery, dependency graphs, and resource locks.

## Highlights

- Machine IDs use `BUG-041` and `SPEC-042`.
- Human labels use `BUG-041 P1 AA Recent Diagnostics`.
- Workers have unique machine names and labels, such as `BUG-041-impl-w01` and `BUG-041 P1 AA Recent Diagnostics [impl w01]`.
- Closed, partial, blocked, and verified-like states require Evidence.
- Browser, API, and SQL evidence use structured Artifacts instead of free-form strings.
- The validator checks the state matrix, concurrency, Heartbeat, Run/Attempt/Lease, dependency cycles, and resource locks.
- The core contract is platform-neutral; the Resolver selects an Adapter from portable capability and model requests, then records actual values in Resolution.
- Adapter protocol v1 makes Worker transport, inputs, timeouts, and output paths machine-readable.
- Task and Evidence use Schema v2; legacy documents can be upgraded with the migration script.

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
| `single-worker` | One Worker implements and verifies the task |
| `batch-worker` | One Worker covers 2-4 similar Tasks with independent conclusions |
| `full-dispatch` | Cross-project, database, release, migration, or high-risk real-chain work |

## Model Adapters

The core uses four portable `reasoning_profile` values. The Codex Adapter currently uses `gpt-5.6-sol` and maps them as follows:

| Core profile | Codex value |
| --- | --- |
| `fast` | `low` |
| `standard` | `medium` |
| `deep` | `high` |
| `critical` | `xhigh` |

The machine contract is defined by [codex.adapter.json](references/adapters/codex.adapter.json). [external-cli.adapter.json](references/adapters/external-cli.adapter.json) demonstrates different Worker commands, monitoring, and reasoning values without changing the core Schema.

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
- Heartbeat metadata and concurrency limits.
- Loaded board dependencies and dependency cycles.
- Active resource locks, active holder Runs, and Lease bounds.

```bash
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml
python3 scripts/validate_pm_dispatch.py --tasks-dir docs/tasks
```

## Self-Test

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py tests/*.py
for file in references/schemas/*.json references/adapters/*.adapter.json; do python3 -m json.tool "$file" >/dev/null; done
```

Dry-run legacy migration before explicitly writing files:

```bash
python3 scripts/migrate_pm_dispatch.py docs/tasks
python3 scripts/migrate_pm_dispatch.py docs/tasks --write
```

Write mode validates complete v2 output, preserves the source as `.v1.bak`, and then performs an atomic replacement. The task panel uses deterministic status mapping and snapshot tests:

```bash
python3 scripts/render_task_panel.py --tasks-dir docs/tasks
```

## Sources Of Truth

- `SKILL.md`: execution order and progressive-disclosure routing.
- `references/core-contract.md`: platform-neutral invariants.
- `references/adapters/*.adapter.json`: machine-readable Provider policies.
- `references/adapters/*.md`: Provider instructions.
- `references/operating-model.md`: directory, Task, Evidence, and Prompt examples.
- `references/schemas/`: formal data structures.
- `scripts/validate_pm_dispatch.py`: Gate, dependency, and lock validation.
- `scripts/resolve_pm_dispatch.py`: capability, model, and fallback resolution.
- `scripts/adapter_protocol.py`: Worker operation envelopes and provider-result decoding.
- `scripts/migrate_pm_dispatch.py`: conservative migration to Schema v2.
- `scripts/render_task_panel.py`: deterministic five-column task panel rendering.
- `tests/`: persistent Adapter, Resolver, migration, and Gate regression tests.

Schemas, Adapter JSON, and the validator are authoritative. The README does not redefine fields.

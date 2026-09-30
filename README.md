# PM Dispatch Development

English | [简体中文](README.zh-CN.md) | [Measurement Notes](references/usage-evidence.md)

A delivery-management skill for coding agents: turn bug fixes and feature requests into recoverable work with a compact task board, reusable Workers, and evidence-based acceptance. PM means project manager: the coordinating agent in the current conversation.

Best suited to ongoing work across sessions or repositories. Small, low-risk fixes can stay in the current conversation without a Worker. This is a Skill plus local Python tooling, not a hosted service or an MCP runtime proxy.

## Measured, Not Promised

One anonymized project snapshot, measured on **2026-09-04**:

| Observation | Result | Meaning |
| --- | ---: | --- |
| Canonical task records | **48** | 37 bugs, 10 features, 1 release; excludes 2 template/alias documents |
| Default actionable panel | **1,928 characters** | Compared with 9,472 for the all-task panel: **79.65% less text** |
| Historical board vs actionable panel | **27,038 → 1,928 characters** | **92.87% less text** for current decisions, not equivalent-content compression |
| Stored prompt files | **190** | Historical prompt documents, not 190 model calls |

These are Unicode character counts from a mixed-version, single-project sample. They are **not measured token, cost, speed, or success-rate improvements**. Filtering removes closed/irrelevant details from the default view. See [scope, formulas, and reproduction](references/usage-evidence.md).

## Frequent Workflows

The examples below reflect recurring use patterns; the task-type distribution above is the only measured frequency.

| When | Request after invoking the Skill | Result |
| --- | --- | --- |
| Daily triage | "Show actionable tasks and one next step each." | Five-column board; up to 8 rows by default |
| Bug repair | "Dispatch BUG-001; keep monitoring in this conversation." | Visible Worker, frozen scope, focused checks, evidence report |
| Feature delivery | "Dispatch SPEC-002 through implementation and browser acceptance." | One Worker reused across Gates; only new scope/evidence sent |
| Interrupted work | "Reconcile the original Worker before replacing it." | Recover from Run/Attempt/Lease and persisted milestones |
| Environment-blocked acceptance | "Separate completed code from missing live API or browser evidence." | Honest partial/blocked result and one unblock action |

Release/migration and cross-repository work use the same records with broader verification and dependency/lock checks. Git commits, pushes, production changes, and visible task creation still require the user's requested scope and the host's permissions.

## Quick Start

Use the installation convention supported by your host. This repository's existing Codex setup uses:

```text
~/.codex/skills/pm-dispatch-development
```

```text
Use $pm-dispatch-development to triage this bug, choose the lightest strategy,
and report verified progress and the next action.
```

Local helpers require Python 3.11+; the lock-based helpers use POSIX `fcntl` (macOS/Linux). Native Windows is not validated. Core JSON and supported YAML-subset files need no third-party dependency; general YAML may require PyYAML.

Codex execution follows [live host capabilities](references/adapters/codex-routing.md): native internal agents use parent completion notifications; visible desktop Workers require the task/Heartbeat tools. Internal agents are not visible background threads and cannot promise monitoring across disconnection. When neither path is supported, use `direct` where scope permits. Optional external delegation remains inactive unless explicitly requested and permitted; no external agent, credential, or model is bundled.

## How It Works

```text
One project PM conversation
  -> internal native Worker + parent completion notifications
  OR visible Worker + task Heartbeat on the same PM
  -> reuse the selected Worker across related work and Gates
  <- evidence, latest milestone, and one next action
```

Reuse the project PM across bugs and features. If context reduction is insufficient, prepare a compact handoff and obtain user approval before creating a replacement PM. Keep existing Workers through the transfer; Run count alone never forces replacement. See [coordinator migration](references/project-coordinator.md).

| Term | Purpose |
| --- | --- |
| Worker | An execution agent/task that implements the assigned scope |
| Task | Stable scope, dependencies, acceptance, and quality checks |
| Runtime | Resolution, Worker IDs, ownership, events, and current execution |
| Evidence | Structured artifacts supporting a result |
| Run / Attempt | A unit of execution / its recoverable execution attempt |
| Lease | Time-bounded ownership, not proof of progress |
| Gate | A validation checkpoint that requires the declared evidence |

Machine records are Task v4, Runtime v1, and Evidence v2. Keep lifecycle, verification, blockers, and closure separate. A passed build is not automatically end-to-end acceptance.

Use `BUG-001 P1 API Fix pagination` for a display label: ID, priority, area, then title. Area names are project-defined. Examples here are fictional, not exported task titles. L0-L4 are this Skill's evidence levels, not industry certification; artifact requirements live in [the closure contract](references/closure.md).

## Bounded Overhead

| Control | Default | What the number does not prove |
| --- | --- | --- |
| Scheduled inspections | 10 minutes, at most 6 scheduled checks/hour | Compared with 5 minutes, 50% fewer scheduled opportunities; ad hoc checks remain possible |
| Positive terminal waits | 1 per Run, at most 30 seconds | Limits requested blocking time, not billed tokens or total transport latency |
| Worker prompts | 6,000 initial / 3,000 continuation characters | 50% lower continuation cap, not measured cache savings |
| Batch dispatch | 2-4 tasks per Worker | 50-75% fewer Worker creations than one per task, when batching is appropriate |
| Recovery | 1 same-method retry, up to 2 alternatives | Bounded recovery, not guaranteed success |

The 10-minute monitor stays in the dispatching conversation; no second monitor task is created. Its planner is deterministic and model-free, but **a host-scheduled Heartbeat may still consume model tokens**. The Skill cannot hide native MCP calls or keep a disconnected host running. Authorization and optional session audits detect violations; outages retain ownership until reconciliation.

## Choose A Strategy

- `direct`: a small, low-risk change in this conversation.
- `single-worker`: implementation, integration, repair, and verification in one reusable Worker.
- `batch-worker`: 2-4 related tasks sharing a project/Gate, with separate conclusions.
- `full-dispatch`: high-risk or cross-project work with ordered dependencies and broader evidence.

Codex child Workers use the dispatch host's default model; temporary parent-task model overrides are not automatically copied. `fast`/`standard` inherit effort; `deep`/`critical` map to `high`. Other hosts need an adapter that implements the declared operations; the bundled [external CLI adapter](references/adapters/generic.md) is a portability example, not a prebuilt provider integration.

## Inspect And Validate

Run these from the Skill directory; replace the project placeholder with your own local path:

```bash
PROJECT=/path/to/project
python3 scripts/render_task_panel.py --tasks-dir "$PROJECT/docs/tasks"
python3 scripts/validate_pm_dispatch.py --tasks-dir "$PROJECT/docs/tasks"
python3 scripts/measure_context_baseline.py --tasks-dir "$PROJECT/docs/tasks" \
  --board "$PROJECT/docs/dispatch-board.md" --public \
  --output /tmp/pm-public-baseline.json
python3 -m unittest discover -s tests
python3 scripts/validate_skill_consistency.py
```

The built-in panel renderer currently uses Chinese display labels; [the panel reference](references/task-panel.md) provides their English meanings. Agent explanations follow the user's language. Schema keys and status enums do not change with language.

## Privacy And Limits

Only `measure_context_baseline.py --public` uses a numeric, fixed-label export allowlist. Normal panels, Task/Evidence, prompts, session logs, and snapshots can contain private text; they are **not automatically redacted**. Do not publish them or local backups. Ignore rules do not remove previously tracked files or Git history.

No production project names, home-directory paths, task titles, Worker IDs, credentials, or raw sessions are included in the published measurement. Aggregation removes direct identifiers; it is not a formal anonymity guarantee.

## Reference Map

- [SKILL.md](SKILL.md): concise agent instructions and on-demand routing.
- [Core contract](references/core-contract.md): state, dependency, lock, and Gate invariants.
- [Task examples](references/task-examples.md): fictional record fragments.
- [Prompts](references/prompts.md): stable prefixes, deltas, and short Heartbeat.
- [Codex adapter](references/adapters/codex.md): provisioning and bounded monitoring.
- [Context budget](references/context-budget.md): read limits and Coordinator saturation.
- [Measurement notes](references/usage-evidence.md): evidence and reproducible public metrics.

Schema, Adapter JSON, Resolver, and Validator are authoritative. Documentation does not redefine the machine contract.

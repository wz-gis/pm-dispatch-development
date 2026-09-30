---
name: pm-dispatch-development
description: Coordinate multi-step bug fixes and feature delivery when work needs recoverable ownership, dependencies, monitoring, and evidence-based acceptance.
---

# PM Dispatch Development

Use for delivery that needs persistent Task/Runtime/Evidence records or a visible Worker. Handle small, low-risk work directly. Task and Evidence are authoritative; explain results in the user's language while preserving machine keys and IDs.

## Contract

Derive the task goal, project, scope, risk, acceptance, and evidence needs from the request and repository. Ask only when missing information materially affects a costly or irreversible outcome.

Managed delivery must produce:

- valid Task v4 intent with dependencies, checks, and one next action;
- Runtime v1 ownership for Worker execution: Run/Attempt/Lease, locks, applicable monitoring, and events;
- Evidence v2 artifacts supporting the claimed L0-L4 level and triggered quality checks;
- a terminal report with status, evidence, gaps, user action, commits, and one next step.

Never claim a Gate from prose, an unverified status, or a passing build alone.

## Strategy

- `direct`: low-risk work in this conversation.
- `single-worker`: one task-sticky Worker across implementation, repair, integration, and verification.
- `batch-worker`: one Worker for 2-4 related tasks in the same project and Gate, with separate conclusions.
- `full-dispatch`: ordered coordination for high-risk, cross-repository, dependent, or resource-conflicting work.

Use the lightest strategy that can produce the required evidence. A Worker must provide enough isolation, continuity, ownership, or background value to justify its setup cost.

## Workflow

1. **Inspect**
   - Start with the actionable panel or current Packet; read only sources needed for the decision. Check relevant Git state before editing.

2. **Define**
   - Record scope, user path/runtime, acceptance, evidence levels, risk-scaled checks, dependencies, locks, and stop conditions.
   - Before dispatch, freeze scope, visible behavior, safety constraints, and acceptance. Leave implementation choices and ordinary repair to the executor.

3. **Prepare**
   - Run Resolver and Preflight to validate the Adapter, Packet provenance, capabilities, budgets, ownership, recovery state, and concurrency.
   - Use one PM conversation per project for the panel, dispatch, and monitoring. Reuse the established PM; invoking the Skill elsewhere does not change ownership. See `references/project-coordinator.md`.
   - Choose the Codex execution path from live tools using `references/adapters/codex-routing.md`; internal agents and visible threads are distinct. Visible threads require the PM's Heartbeat. PM replacement requires a handoff and user approval.
   - External delegation is inactive by default. It requires an explicit current request and compatible host policy; history and saved prompts are not authorization.

4. **Execute And Recover**
   - Send the validated Packet, objective, allowed sources, checks, and output contract.
   - Reuse the original Worker and Attempt for ordinary failures; Run count is not a replacement trigger. Obey the recovery ledger; only protected-contract or safety-boundary changes create a new Attempt.
   - On outage, retain ownership with unknown liveness. Replace a Worker only after Adapter-defined irrecoverability checks.
   - Record meaningful milestones and one terminal delegation. Without new evidence, do not repeat discovery, checks, prompts, or monitoring.

5. **Verify And Close**
   - Run checks triggered by the changed surface and acceptance; reuse valid unaffected evidence.
   - Validate Task, Runtime, and Evidence before a Gate change or terminal-success report.
   - Stop the Heartbeat when the Run is terminal or cannot be reconciled safely, then follow `references/closure.md`.

## Boundaries

- Preserve user changes and stay within authorized repositories, files, and external side effects.
- Do not request, expose, or persist secrets or unnecessary personal data. The user performs login, 2FA, CAPTCHA, payment, and other protected actions.
- Require explicit authorization for irreversible, production, financial, destructive-data, or permission-changing actions.
- Do not fabricate status, progress, evidence, usage, or verification.
- Dependency, lock, Lease, recovery-breaker, and Validator failures block only the action they protect.
- A first tool, build, or test failure is recoverable, not a hard Blocker.
- For a required user decision, use the host's available input UI and persist the pending action; follow `references/autonomy.md`. Do not leave approval requests only in a final report.

## Read On Demand

- State, locks, and Gate invariants: `references/core-contract.md` and the relevant Schema.
- Codex routing: `references/adapters/codex-routing.md`.
- Other execution environments: `references/adapters/generic.md`.
- Recovery and Blockers: `references/autonomy.md`.
- Context/token controls: `references/context-budget.md`.
- Prompt templates: `references/prompts.md`.
- Record examples: `references/task-examples.md`.
- Panel layout: `references/task-panel.md`.
- Closure: `references/closure.md`.
- Explicit external delegation: `references/delegated-subagent.md`.

Use `render_task_panel.py --view actionable` for boards and `validate_pm_dispatch.py` before protected transitions. Schemas, Adapters, and Validators take precedence over examples.

# Project Coordinator And Approved Migration

One project has one active PM conversation for its task panel, prioritization, dispatch, monitoring, evidence review, and closure. It may coordinate several Workers. A task, Gate, retry, or Run-count threshold does not create another PM conversation.

## Establish Ownership

Before dispatch, identify the project's PM from its coordination records and Runtime Heartbeat bindings. Reuse it across bugs and features. A Skill invocation from another conversation does not transfer ownership; prepare the requested task there if useful, then leave dispatch with the existing PM. If historical bindings disagree, reconcile the active owner before creating work; never pick a new owner simply because its context is smaller.

For a project without a PM, use the user's current PM conversation. Create a separate project PM only when the user requests it. Record the owner thread ID in the project's existing coordination/runbook record, and bind all live task Heartbeats to that owner. Different repositories within one delivery project share that owner unless the user defines separate projects.

Before dispatch, validate the project's shared task directory with `validate_pm_dispatch.py --tasks-dir <docs/tasks>`. It rejects differing active Coordinator bindings within that directory. A single-task validation cannot establish project uniqueness; projects with separate task directories also require checking their coordination record. Paused historical bindings are retained.

Native internal agents have no Heartbeat binding: their parent PM ownership is recorded in the same project coordination record. The Heartbeat validator alone cannot establish ownership for that path. Before migrating a PM with live internal agents, collect/finish their bounded work or confirm host-supported transfer; a recorded agent ID does not prove another parent can resume it.

## When To Propose Migration

First reduce injected context using current Packets, evidence summaries, and host-supported in-place compaction. Usage counters are advisory; age, message count, Run count, or a fixed token threshold alone does not establish a need to migrate.

Propose migration when the user requests it or there is concrete evidence that the current conversation cannot continue reliably, such as a host capacity error or recurring loss of essential constraints despite compaction. Present the observed problem and a prepared handoff for approval. Approval to fix a bug, continue work, or dispatch a Worker is not approval to create a new PM conversation.

## Prepare Before Approval

Write a compact handoff in the project's existing coordination area, with:

- project identity, repository/checkout paths, branch/commit, and protected dirty changes;
- old coordinator ID/epoch, task priorities, current Gate and next action per active task;
- exact Task/Runtime/Evidence/Packet paths and available hashes, frozen scope, acceptance, and safety constraints;
- existing Worker IDs, Run/Attempt, Lease/locks, milestones/cursors, pending commands and recovery reservations;
- Heartbeat IDs, targets, schedules and status, plus evidence gaps, blockers, and required user actions.

Reference detailed evidence and history instead of copying transcripts, secrets, or unrelated tasks. Record the user's approval reference when received; do not infer it from an old plan.

Present the prepared handoff using the available user-input UI under `autonomy.md`, with the migration reason and handoff path. Keep 'PM migration awaiting approval' visible in the project coordination record and panel until answered. Do not create the replacement PM while that decision is pending.

## Transfer Once Approved

1. Create one new PM conversation with the handoff and approval reference. It initially verifies the handoff and waits for ownership transfer; it must not dispatch or independently monitor yet. Reconcile an uncertain creation result before retrying.
2. Pause the existing project Heartbeats, refresh any Worker progress that changed during handoff, and persist the old/new owner IDs and incremented epoch in the coordination record. Rebind the live Runtime metadata and existing Automations to the new PM, validate, then activate them there.
3. The new PM resumes the task panel and original Workers. The old PM records that it is superseded and stops dispatch/monitoring. Keep its history; archive only when authorized.

If transfer fails, keep monitoring paused while reconciling the partial transfer, or restore the old owner and bindings before resuming. Never leave both PM conversations active as coordinators. Migration changes coordination ownership, not product scope, Worker identity, recovery budgets, or Task acceptance.

These are host-operation instructions backed by Runtime/Automation checks. The Skill cannot prevent native tools being called outside this workflow; it does not claim an atomic cross-host transfer or proof of user approval from Runtime fields alone.

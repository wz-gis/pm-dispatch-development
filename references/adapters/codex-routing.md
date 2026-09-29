# Codex Execution Routing

Read before selecting a Codex Worker. An execution Adapter is not a model/provider override. `codex` identifies visible desktop threads; `codex-subagent` identifies native internal agents. Both keep the existing project PM and inherit model settings unless the user explicitly requests an override.

## Select Once From Live Capabilities

Inspect this session's callable tool declarations, including deferred tools when discovery is available. Save their exact names as a JSON string array and run:

```sh
python3 scripts/select_codex_execution.py --tools /tmp/host-tools.json --completion-notifications
```

Pass `--completion-notifications` only when the host explicitly documents delivery of internal-agent terminal notifications to this parent. Tool names alone do not prove callbacks, permissions, workspace isolation, or persistence.

Native dispatch requires creation, continuation, and verified parent completion delivery. Waiting, interruption, and closing are separate optional operations, not universal creation prerequisites. The selector recognizes `followup_task` and `send_message` as continuation candidates alongside `send_input`; `interrupt_agent` is an interruption candidate, NEVER an alias for `close_agent`.

`action=bind-host-tools` means the execution path exists but native arguments need binding. Read the relevant live declarations once and prepare the binding below; do not call this `direct`, ask for user approval to map ordinary parameters, or guess argument names. `action=ready` means tool binding is complete, not that a Worker was created or execution was authorized.

- Ordinary authorized delegation: prefer native internal agents when supported. Use `codex-subagent` in Task provider policy and allowed providers; `heartbeat_required=false`, monitor mode `milestone`. Read `codex-subagent.md`.
- Explicit visible/new/background thread, or required durable periodic monitoring: pass `--require-visible`. Use `codex` only if the complete visible tool path and host authorization are available; read `codex.md`. Do not silently downgrade a visibility or monitoring requirement.
- Neither path available: perform the work in the current PM using `direct` when scope permits. Explain the missing capability once; do not retry discovery unchanged, infer missing account permissions, or repeatedly ask the user to approve an unavailable tool.

The selector reports capability, not authorization to spawn. Follow the actual host tool restrictions. For a visible thread, satisfy any required explicit user request and project selection. For native agents, delegate only bounded work that adds value; keep urgent tightly coupled work local.

Feed the selected policy to Resolver, then run normal Preflight. Pass the same inventory to both with `--host-tools` so unavailable tools fail before creation. Do not copy `background-worker`, `heartbeat`, browser, or database capabilities from a visible task into an internal task unless the new route actually supplies them. Retain real acceptance and safety requirements; if they cannot be met, keep execution local or report that specific limitation.

## Host Binding

For alternate signatures, use a JSON object instead of a names-only array. It contains `tools` (the exact live names) and `native_agent_bindings` (operation bindings). Store it with the existing task/coordinator artifacts and reuse it while the live declarations remain unchanged; do not store credentials or entire conversation histories.

Each binding has `tool`, `schema_verified: true`, and `input_map`. Set `schema_verified` only after reading that tool's current declaration and checking its semantics; an explicitly verified role can use a different live name without another Skill code change. Map canonical fields to the real native parameter names: `create` needs `prompt`; `send` needs `worker_id` and `prompt`; optional `wait` needs `worker_id` and `timeout_ms`; `cancel` and `interrupt` each need `worker_id`. If the host expects a list of IDs, set `list_inputs: ["worker_id"]`. Optional `result_paths` maps canonical `worker_id`, `submission_id`, `status`, `timed_out`, or `previous_status` to declared `$.field` paths. Do not invent a submission ID or completion status from a generic acknowledgement.

The binding is an inspected declaration, not machine proof of host semantics. For continuation, check that the tool addresses the same existing Worker and obey its active/completed-state preconditions; a follow-up tool that starts a different Worker is not sticky reuse. Non-equivalent APIs require a dedicated Adapter rather than a false alias. The bundled defaults remain the documented `spawn_agent/send_input/wait_agent/close_agent` signatures. A role with no usable tool stays unavailable; absence of an optional role does not block dispatch.

Pass this same file to `adapter_protocol.py --host-tools` for native invocation/result decoding and to `authorize_terminal_wait.py --host-tools` when waiting. Use the returned exact `target` and `native_arguments`. Resolver and Preflight accept the same object. Never run a hard-coded default invocation after selecting an alternate binding.

## Existing Runs

Reuse an existing Worker through its original Adapter. A missing tool is not Worker death and does not authorize switching transport, creating a duplicate Worker, or moving the PM. Preserve its ID, Attempt, locks, evidence, and unknown liveness. Resume when its tool path returns, or apply the existing irrecoverability/recovery rules. Never overwrite an active Run's Resolution to fit today's tools.

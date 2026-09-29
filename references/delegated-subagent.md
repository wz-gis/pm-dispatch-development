# Optional External Sub-agent

Load only when the user's current request explicitly selects an external implementation agent and host policy permits it. Historical prompts, saved plans, or installed definitions are not authorization. Otherwise use the resolved Codex path.

## Contract

```yaml
dispatch:
  delegation:
    mode: thin-wrapper-subagent
    agent: <verified-local-alias>
    initial_invocation_limit: 1
    repair_invocation_limit: 1
    retry_policy: focused-verification-failure-only
```

The alias identifies a locally installed definition, not a portable model ID. Verify it without invoking it. Do not invent or substitute a provider, change credentials, or expose private endpoints.

## Ownership

```text
current PM conversation + Heartbeat
  -> one visible Codex Worker
       -> one bounded external implementation call
```

The PM owns Task/Runtime, design freeze, Packet, monitoring, and closure. The visible Worker owns the checkout, invokes the external agent, reviews its diff, runs focused verification, commits accepted work, and returns Evidence. The external agent may edit only authorized sources and run relevant tests; it does not own PM state, monitoring, Worker creation, or commits.

## Invocation

Use the separately installed `sub-agents` Skill and its discovery protocol. Invoke the selected definition from the visible Worker's checkout with only the Packet path/SHA, objective, allowed sources, verification commands, and output contract.

One initial call is allowed. A launch failure before execution may retry the same logical call. After execution starts, inspect the produced artifacts before deciding what remains. One differential repair call is allowed only when focused verification provides concrete failing evidence; otherwise stop.

# Thin Wrapper Sub-agent

Load for "Gemini execute", "DeepSeek execute", "thin-wrapper mode", or an explicit request for a visible Codex Worker backed by an external agent. Chinese aliases `Gemini执行`, `DeepSeek执行`, and `薄壳模式` remain supported.

## Short Invocation

```text
$pm-dispatch-development Gemini execute SPEC-002
```

Expand without asking the user to repeat the topology or recovery contract:

```yaml
strategy: single-worker
delegation:
  mode: thin-wrapper-subagent
  agent: gemini-flash
  initial_invocation_limit: 1
  repair_invocation_limit: 1
  retry_policy: focused-verification-failure-only
```

Agent names are **local definition aliases**, not globally available model IDs. Preserve an explicitly requested installed definition. When present, the existing Gemini aliases are `gemini-flash-low` for `fast` and `gemini-flash` for other profiles; explicit DeepSeek execution uses `deepseek-flash`. Read the installed definition for its actual provider/model/effort. Do not publish private endpoints or credentials, invent a missing definition, or silently substitute another provider. A Pro/review route requires an explicit request and a matching installed definition.

These selections affect only the external agent. The visible Codex Worker retains its normal host-default model and Adapter effort rules. Local definitions are not changed by this documentation.

## Topology And Ownership

```text
current PM conversation + Heartbeat
  -> one user-visible Codex Worker
       -> one external implementation invocation
```

The PM owns Task/Runtime, design freeze, Packet, and same-conversation Heartbeat; it never invokes the implementation sub-agent directly. Heartbeat monitors the visible Worker, not the external process.

The visible Worker validates the Packet, records a milestone, invokes from its own checkout, inspects the returned diff, runs focused verification, commits accepted changes, and returns Evidence. It does not repeat repository-wide discovery or implement a competing solution.

The external agent edits only authorized code and runs initial relevant tests. It cannot create agents, edit PM state, update the board, monitor, or commit.

## Invoke

Requires the separately installed `sub-agents` Skill. Follow its discovery protocol, then invoke the selected definition once:

```bash
SUBAGENT_SKILL=/path/to/installed/sub-agents
AGENT=gemini-flash
python3 "$SUBAGENT_SKILL/scripts/run_subagent.py" --list
python3 "$SUBAGENT_SKILL/scripts/run_subagent.py" \
  --agent "$AGENT" \
  --prompt "<compact objective plus Packet path/SHA>" \
  --cwd "$PWD" --timeout 1200000
```

Set AGENT to a verified installed alias before running. Discovery is not a model invocation. `--cwd "$PWD"` must point to the visible Worker's checkout. Send Packet path/SHA, one objective, exact source paths, verification commands, and output fields, not PM history.

## Recovery

- Success: inspect changed paths and run focused verification.
- Pre-execution launch/configuration failure: repair and retry the same logical invocation in the same Worker/Attempt.
- Partial result or timeout after execution began: inspect Artifacts first; do not automatically restart.
- One differential repair call is allowed only after concrete focused-verification failure. Send failure, diff, Packet SHA, and expected correction.
- No failing evidence means no second call. Ordinary repair does not create another visible Worker or Attempt.

Stop when focused verification passes and commit/files, Artifact IDs, remaining risk, and one next action are returned.

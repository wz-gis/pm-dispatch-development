# Generic Adapter

Use a non-Codex machine Adapter when another execution environment owns Worker creation. `external-cli.adapter.json` is the bundled portability example.

Declare Worker, Reasoning, Monitor, and Evidence components according to `adapter.schema.json`. Worker protocol v2 requires create/send/inspect/wait/rebind/collect/cancel operations, normalized status mapping, result paths, and idempotency policy. Persist returned continuation tokens and event cursors in Runtime. A generic Adapter without a `model` component leaves `model_id` null; a Provider may add its own declared model route when needed.

Declare an unavailable operation with `supported=false`; the protocol builder rejects invoking it. A received completion event may still be decoded for collection. Never invent a status probe or persistent rebind operation just to fill the operation set.

Run the Resolver to create `dispatch.resolution`, generate and validate the Context Packet plus prompt, then build the operation envelope with `scripts/adapter_protocol.py`. Keep every Run consistent with that actual resolution and persist the provider's real worker identifier. Use `strict` for pinned execution and `compatible` only for explicitly allowed Provider or manual-monitor fallbacks. Provider payloads receive the compact Packet or its content, not a default dump of Task/Evidence/history.

For `event-lease`, declare a Provider-native `event_wait_target`, Lease renewal support, and `inspect` as the metadata-only disconnect probe. Wait until terminal activity or Lease expiry; probe only at expiry. Providers without this surface must use their declared heartbeat, poll, or explicit manual fallback.

If the platform has no compatible managed Worker surface, use `direct` or an explicitly supported `ci-job`/`human` path. A native parent-scoped agent can be a managed Worker without durable background support; do not claim `background-worker` for it. Preserve the Task/Evidence contract and the ownership/lock records applicable to the selected strategy.

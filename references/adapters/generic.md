# Generic Adapter

Use a non-Codex machine Adapter when another execution environment owns Worker creation. `external-cli.adapter.json` is the bundled portability example.

Declare Worker, Reasoning, Monitor, and Evidence components according to `adapter.schema.json`. Worker protocol v2 requires create/send/inspect/wait/rebind/collect/cancel operations, normalized status mapping, result paths, and idempotency policy. Persist returned continuation tokens and event cursors in Runtime. A generic Adapter without a `model` component leaves `model_id` null; a Provider may add its own declared model route when needed.

Run the Resolver to create `dispatch.resolution`, build the operation envelope with `scripts/adapter_protocol.py`, keep every Run consistent with that actual resolution, and persist the provider's real worker identifier. Use `strict` for pinned execution and `compatible` only for explicitly allowed Provider or manual-monitor fallbacks.

For `event-lease`, declare a Provider-native `event_wait_target`, Lease renewal support, and `inspect` as the metadata-only disconnect probe. Wait until terminal activity or Lease expiry; probe only at expiry. Providers without this surface must use their declared heartbeat, poll, or explicit manual fallback.

If the platform cannot create background workers, use `direct`, `ci-job`, or `human` execution and keep the same Task, Evidence, Run, Attempt, Lease, dependency, and resource-lock contracts.

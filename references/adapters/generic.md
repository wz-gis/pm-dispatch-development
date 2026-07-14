# Generic Adapter

Use a non-Codex machine Adapter when another execution environment owns Worker creation. `external-cli.adapter.json` is the bundled portability example.

Declare Worker, Model, Monitor, and Evidence components according to `adapter.schema.json`. Worker protocol v1 requires a transport and structured create/inspect/cancel operations with inputs, timeouts, and output paths. A provider may split reasoning profiles across specialized models; every core profile needed by a Task must resolve to one declared model mapping. The core never assumes provider values are Codex-style `low` or `high`.

Run the Resolver to create `dispatch.resolution`, build the operation envelope with `scripts/adapter_protocol.py`, keep every Run consistent with that actual resolution, and persist the provider's real worker identifier. Use `strict` for pinned execution and `compatible` only for explicitly allowed Provider/model/manual-monitor fallbacks.

If the platform cannot create background workers, use `direct`, `ci-job`, or `human` execution and keep the same Task, Evidence, Run, Attempt, Lease, dependency, and resource-lock contracts.

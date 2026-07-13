# Generic Adapter

Use a non-Codex machine Adapter when another execution environment owns Worker creation. `external-cli.adapter.json` is the bundled portability example.

Declare Worker, Model, Monitor, and Evidence components according to `adapter.schema.json`. Map all four core reasoning profiles to the provider's native values. The core never assumes those values are Codex-style `low` or `high`.

Run the Resolver to create `dispatch.resolution`, keep every Run consistent with that actual resolution, and persist the provider's real worker identifier. Use `strict` for pinned execution and `compatible` only for explicitly allowed Provider/model/manual-monitor fallbacks.

If the platform cannot create background workers, use `direct`, `ci-job`, or `human` execution and keep the same Task, Evidence, Run, Attempt, Lease, dependency, and resource-lock contracts.

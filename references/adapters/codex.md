# Codex Adapter

Use this adapter when `task.yaml.dispatch.resolution.provider` is `codex`.

The machine contract is `codex.adapter.json`. Protocol v1 uses the `tool` transport with structured `create_thread`, `read_thread`, and `set_thread_archived` operations. It currently uses `gpt-5.6-sol` and maps portable reasoning profiles to Codex reasoning effort:

| Core profile | Codex effort |
| --- | --- |
| `fast` | `low` |
| `standard` | `medium` |
| `deep` | `high` |
| `critical` | `xhigh` |

Run `scripts/resolve_pm_dispatch.py` before creation, then build the `create` envelope with `scripts/adapter_protocol.py`. Execute the declared tool with the exact `resolution.model_id` and `resolution.provider_reasoning_effort`; decode the returned thread ID through `worker_id_path` and persist it as `worker_id`. Do not mark a Run active before a real worker ID exists.

Use `worker_label` as the visible thread title. Example:

```text
SPEC-042 P1 WEB 新增页面 [impl w01]
```

When heartbeat monitoring is authorized, persist its automation ID, interval, maximum checks, stop condition, lightweight flag, and status. If thread creation or heartbeat setup is unavailable, record `THREAD_BLOCKED`; do not claim the Adapter was used only by writing metadata.

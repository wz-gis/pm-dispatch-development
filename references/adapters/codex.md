# Codex Adapter

Use this adapter when `task.yaml.dispatch.resolution.provider` is `codex`.

The machine contract is `codex.adapter.json`. It currently uses `gpt-5.6-sol` and maps portable reasoning profiles to Codex reasoning effort:

| Core profile | Codex effort |
| --- | --- |
| `fast` | `low` |
| `standard` | `medium` |
| `deep` | `high` |
| `critical` | `xhigh` |

Run `scripts/resolve_pm_dispatch.py` before creation. Create a visible Codex thread with the exact `resolution.model_id` and `resolution.provider_reasoning_effort`, then persist the returned thread ID as `worker_id`. Do not mark a Run active before a real worker ID exists.

Use `worker_label` as the visible thread title. Example:

```text
SPEC-042 P1 WEB 新增页面 [impl w01]
```

When heartbeat monitoring is authorized, persist its automation ID, interval, maximum checks, stop condition, lightweight flag, and status. If thread creation or heartbeat setup is unavailable, record `THREAD_BLOCKED`; do not claim the Adapter was used only by writing metadata.

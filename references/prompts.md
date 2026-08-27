# Worker Prompts

## Worker

```markdown
【稳定执行契约；所有 Worker 保持原文和顺序】
恢复：普通失败留在本 Worker/Attempt；1 次同方法重试，最多 2 种替代路径，随后 1 次聚焦复验
通知：仅在方案确认、核心编辑完成、复验完成、不可逆边界、终态发送 1-2 句里程碑
Lease：每条通知携带 progress_seq；终态 delegation 前更新最后进度。不要自行创建并行替代 Worker
终态 delegation：status、run/attempt、commit/files、verification artifact IDs、hard blocker/user action、next action

【动态任务后缀；不得放在稳定前缀之前】
任务：SPEC-042 P1 WEB 新增页面
身份：SPEC-042-impl-w01 / run-SPEC-042-impl-w01 / attempt-SPEC-042-impl-w01-a01
Resolution：provider=codex，model_id=null（发布端默认模型），reasoning_profile=standard，provider_effort=inherit
冻结设计：<design_fingerprint>
目标与用户路径：<observable outcome> / <existing-user path>
范围：允许 <repo/files>；禁止 <repos/files>
设计约束：<frozen constraints>
必需证据：commit、files、commands、API/SQL/Browser Artifacts、existing-data regression
资源锁与停止条件：<locks> / <blocked conditions>
```

稳定前缀不得包含 Task ID、Worker ID、时间戳、Run/Attempt、路径或进度；动态字段统一放到后缀以提高可复用前缀命中。分发前冻结设计并复制指纹。`single-worker` 续跑时继续原 Worker，只发送新 Run/Gate、设计指纹、差量目标和证据缺口，不重复粘贴 Skill、Task/Evidence 或历史。

## Milestone

运行中通知只包含 `progress_seq`、“刚完成什么、下一步什么”。PM 收到后更新 `lease.heartbeat_at` 并续租。终态 delegation 一次性回传结构化字段；PM 不周期性全文读取 Task、Evidence 或历史。

## Event-Lease Watchdog

PM 使用 Adapter 的 `event_wait_target` 等待终态事件，超时点等于 `lease.expires_at`。超时只调用一次 `inspect`：仍运行则续租同一 Attempt；终态则收口；不可达则宽限后再探测一次。第二次仍不可达才将 Attempt 置为 `expired`、释放锁并从最后 Artifact/进度恢复。Lease 超时本身不是 Blocker。

## Heartbeat

```markdown
每10分钟在当前分发任务中增量检查 <run_id>/<worker_id>：只读 Worker 状态、Lease、最新里程碑。无变化只续租；里程碑/终态/安全或冻结设计变化才全文收口。监控不可用标 unknown 并保留 Attempt/锁，恢复后 reconcile。不要创建监控 Worker。
```

Heartbeat 必须运行在分发任务线程中，Automation 的 `target_thread_id` 等于 `coordinator_thread_id`，且不得指向 Worker。配置固定为 `context_policy=coordinator`、`scan_scope=incremental`、`lightweight=true`、三项 `read_set`、四项 `full_scan_triggers` 和 `interval_minutes=10`；不得创建第二个监控任务，模板替换后不得超过 240 字符。

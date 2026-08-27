# Codex Adapter

仅在执行或恢复 `provider=codex` 的可见 Worker 时读取本文件。思考强度以 Resolver 生成的 Resolution 为准；模型不由 Skill 指定。

1. 运行 `scripts/resolve_pm_dispatch.py` 写入 Resolution。
2. 冻结设计后运行 `build_context_packet.py`，再用 `validate_context_packet.py` 校验 Packet 与 Worker Prompt。来源漂移、超预算或未经授权的全文读取必须在 create/send 前停止。
3. 运行 `scripts/adapter_protocol.py` 构建 v2 envelope。`create/send/cancel` 使用稳定幂等键；续接原线程用 `send`，断线恢复先 `rebind`，终态经 `wait` 后 `collect`。不得传 `model`；子 Worker 使用发布端默认模型配置。
4. 使用 `worker_label` 作为可见标题；把真实 Thread ID、continuation token 和 event cursor 写入 Runtime 后，才允许 Run 进入 active 状态。
5. 每次 create/send/rebind/cancel 和终态收集后，用 `record_runtime_event.py` 追加对应事件；不要改写已有事件行。
6. 分发前冻结范围、用户可见契约、安全约束和验收项；把 `design_freeze.fingerprint` 复制到 Run。普通失败由原 Worker 在同一 Attempt 内恢复并聚焦复验；只有安全边界或冻结指纹变化才新建 Attempt。
7. 默认采用 `heartbeat`：由分发任务线程每 10 分钟只读取 Worker 状态、Lease 和最新里程碑；里程碑、终态、安全边界或冻结设计变化才读取相关 Task/Evidence 完成收口。Automation 必须指向 `coordinator_thread_id`；不得创建独立监控 Worker/任务。
8. 监控或网络不可用时调用 `reconcile_worker_liveness.py --probe-status monitor-unavailable`，保持原 Attempt 和锁。恢复后先检查原 Worker；只有 Provider 确认身份不可达且宽限复查仍失败才过期 Attempt、释放锁并恢复。
9. `single-worker` 的后续 Run/Gate 使用原 `worker_id`，只发送新 Packet SHA、Gate 和差量；只有 `worker_reuse.replacement_triggers` 允许的原因才能创建替代 Worker。

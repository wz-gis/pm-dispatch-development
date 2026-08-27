---
name: pm-dispatch-development
description: Use when managing software delivery through PM task boards, worker dispatch, Run/Attempt/Lease recovery, dependency and resource-lock safety, structured acceptance evidence, or VERIFIED/BLOCKED closure across one or more projects.
---

# PM 调度式开发

## Principle

Task/Evidence 是事实源，Worker 是可恢复执行器；仅凭机器 Evidence 更新 Gate。可逆即推进，只有硬 Blocker 才停止。

## Fast Execution

选最低足够的模型/effort；无新证据，不新增探索或重复检查；证据足够后立即实施；只验正确性关键路径和必要回归；不为无证据的未来风险扩围；关键验证通过且无新证据即停。

## Load Only What You Need

- 面板运行 `scripts/render_task_panel.py --view actionable`；改格式读 `references/task-panel.md`。
- 创建/修复 Task/Evidence/Runtime 或解释 Validator 错误时读 `references/core-contract.md` 与 Schema。
- 遇到不确定性、恢复失败或准备标记 Blocked 时读取 `references/autonomy.md`。
- 需要 YAML 示例读 `references/task-examples.md`；需要 Worker/Heartbeat Prompt 读 `references/prompts.md`。
- 分发先跑 Resolver/Adapter，再生成并校验 Context Packet；不要把 JSON 加载进上下文；Codex 细则读 `references/adapters/codex.md`。
- Phase 3-6：先生成 Evidence Digest、工程快照、恢复账本，再用 `dispatch_preflight.py` 生成 Packet；不把完整历史注入 Worker。
- 其它 Agent、CI 或人工执行读 `references/adapters/generic.md`。
- Worker 或任务终态时读 `references/closure.md` 收口。
- 修改本 Skill 时运行测试和 `quick_validate.py`。

Schema、Adapter、Resolver、Validator 是机器事实源。Task v4 保存契约，Runtime v1 保存运行态，Evidence v2 保存证据；Task v3 仅兼容读取。

## Naming

ID 用 `BUG-041`；Worker/Run/Attempt 用 `BUG-041-impl-w01`、`run-BUG-041-impl-w01`、`attempt-BUG-041-impl-w01-a01`。类型支持 `BUG`、`SPEC`、`ONBOARD`、`RELEASE`、`ENV`、`CHORE`。

## Strategy

- `direct`：低风险本线程处理。
- `single-worker`：任务级粘性 Worker 跨 Gate 复用。
- `batch-worker`：2-4 个同工程同 Gate 任务共享。
- `full-dispatch`：高风险跨工程链路串行。

默认选最轻的可验证策略；跨 Owner、仓库或资源冲突时升级。

## Workflow

1. **Inspect**
   - 读取 actionable 面板和 Packet，优先使用 Digest/快照；仅受保护触发器允许全文读取，编辑前检查 Git。

2. **Define**
   - 确定类型、优先级、Area、策略、`reasoning_profile`、能力、验收面。
   - 按 Schema 定义用户路径、存量数据、运行形态、L0-L4、质量检查、停止条件、下一步。
   - 分发前冻结范围、用户可见契约、安全约束和验收项并生成指纹。实现方式、文件布局、命令和普通测试失败不属于冻结设计变化。

3. **Check safety**
   - 批量或并行前运行全局 Validator；依赖异常、锁冲突、并发超限、Attempt/Lease 无效时只停止受影响的分发。
   - 首次命令、构建或测试失败不是 Blocker；同一 Worker 做同方法重试、替代路径和聚焦复验，保持同一 Attempt。
   - 同一 Gate 的同一失败指纹最多记录两次同方法失败、三条不同恢复路径；恢复账本打开熔断后，必须先修复契约或设计并显式 reset，禁止盲目新建 Worker。

4. **Dispatch**
   - 运行 Resolver 生成 `resolution`；Task 不接受用户模型 ID。Codex 子 Worker 不传 `model`，跟随发布端的 Codex 默认模型配置；`reasoning_profile` 只映射思考强度。
   - 用 Adapter v2 的 create/send/wait/rebind/collect 执行和续接；幂等键、Worker ID、token、cursor、Run/Attempt/Lease 和锁写入 Runtime，不得伪造 running。
   - 默认使用用户可见 Worker；用户明确允许才使用内部 sub-agent。
   - 分发任务线程每 10 分钟增量检查 Worker、Lease、里程碑；触发时才全文收口，不得再创建独立监控 Worker/任务。
   - 监控不可用时标 `liveness_state=unknown` 并保留 Attempt/Lease/锁；恢复后先 reconcile 原 Worker。Provider 确认不可恢复且宽限复查失败才替换。
   - `single-worker` 的新 Run 和 Gate 默认沿用原 `worker_id`；换 Worker 必须记录允许的 `worker_replacement_reason`，普通 Gate 切换、补测试或补 Evidence 不是替换理由。
   - 只有安全边界或受保护的冻结设计指纹变化时，取消当前 Attempt 并新建 Attempt；普通可恢复问题留在同一 Worker/Attempt 内修复。
   - Prompt 必须通过 Packet 来源、预算和全文权限校验；续跑只发送新 Packet SHA、Gate 和差量。

5. **Verify and close**
   - 回收 commit、文件、命令、API、SQL、Browser、日志、质量检查和发布 Artifact；L0-L4 只能引用 Artifact ID。
   - Validator 自动校验 required/conditional/skipped 质量检查及 Artifact，再更新 Gate；非终态失败留在原 Attempt 修复。
   - 终态必须按 `references/closure.md` 主动报告状态、证据、缺口、用户动作、提交和唯一下一步。

6. **Preflight**
   - 用 `scripts/dispatch_preflight.py` 一次生成并校验 Digest、快照、账本和 Packet；默认输出到 `/tmp/pm-dispatch/<TASK-ID>`。

---
name: pm-dispatch-development
description: Use when managing software delivery through PM task boards, worker dispatch, Run/Attempt/Lease recovery, dependency and resource-lock safety, structured acceptance evidence, or VERIFIED/BLOCKED closure across one or more projects.
---

# PM 调度式开发

## Principle

Task/Evidence 是事实源，Worker 是可恢复执行器；只用机器可校验的 Evidence 更新 Gate。可逆时继续推进，只有硬 Blocker 才停止。

## Fast Execution

1. 选最低足够的模型/effort，关键不确定性才升级。
2. 无新证据，不新增探索或重复检查。
3. 证据足够后立即实施。
4. 只验正确性关键路径和必要回归。
5. 不为无证据的未来风险扩围。
6. 关键验证通过且无新证据即停。

## Load Only What You Need

- 任务面板运行 `scripts/render_task_panel.py`；改格式才读 `references/task-panel.md`。
- 创建/修复 Task/Evidence/Runtime 或解释 Validator 错误时读 `references/core-contract.md` 和 Schema。
- 遇到不确定性、恢复失败或准备标记 Blocked 时读取 `references/autonomy.md`。
- 需要 YAML 示例读 `references/task-examples.md`；需要 Worker/Heartbeat Prompt 读 `references/prompts.md`。
- 分发 Codex Worker 先运行 Resolver 和 Adapter Protocol；脚本消费 Adapter JSON，不要把 JSON 加载进上下文；执行/恢复时读 `references/adapters/codex.md`。
- 其它 Agent、CI 或人工执行读 `references/adapters/generic.md`。
- Worker 或任务终态时读 `references/closure.md` 收口。
- 修改本 Skill 时运行测试和 `quick_validate.py`。

Schema、Adapter、Resolver、Validator 是机器事实源。Task v4 保存契约，Runtime v1 保存运行态，Evidence v2 保存证据；Task v3 仅兼容读取。

## Naming

机器 ID 使用 `BUG-041`；可见名称使用 `BUG-041 P1 AA 最近诊断记录`。Worker、Run、Attempt 使用 `BUG-041-impl-w01`、`run-BUG-041-impl-w01`、`attempt-BUG-041-impl-w01-a01`。类型支持 `BUG`、`SPEC`、`ONBOARD`、`RELEASE`、`ENV`、`CHORE`。

## Strategy

- `direct`：当前线程处理低风险小任务；不创建 Run、Attempt、Lease、Heartbeat 或锁。
- `single-worker`：任务级粘性 Worker 跨 Run/Gate 实现和验证；补验、修复、Gate 切换复用原 Worker。
- `batch-worker`：2-4 个同工程、同 Gate、同回归面任务共享 Worker，各自保留 Task/Evidence。
- `full-dispatch`：跨工程、数据库、发布、迁移、安全或真实链路按 Gate 串行。

默认选择最轻的可验证策略；跨 Owner、仓库或资源冲突时升级。

## Workflow

1. **Inspect**
   - 读取看板、相关 Task/Evidence、Decision、活跃 Run/Lease、依赖和锁；编辑前检查 Git。

2. **Define**
   - 确定类型、优先级、Area、策略、`reasoning_profile`、能力和验收表面。
   - 按 Schema 定义用户路径、存量数据、运行形态、L0-L4、质量检查、停止条件和下一步。
   - 分发前冻结范围、用户可见契约、安全约束和验收项并生成指纹。实现方式、文件布局、命令和普通测试失败不属于冻结设计变化。

3. **Check safety**
   - 批量或并行前运行全局 Validator；依赖异常、锁冲突、并发超限、Attempt/Lease 无效时只停止受影响的分发。
   - 首次命令、构建或测试失败不是 Blocker。同一 Worker 先做一次同方法重试、最多两种不同恢复路径，再做一次聚焦复验；恢复期间保持同一 Attempt。

4. **Dispatch**
   - 运行 Resolver 生成 `resolution`；Task 不接受用户模型 ID。Codex 子 Worker 不传 `model`，跟随发布端的 Codex 默认模型配置；`reasoning_profile` 只映射思考强度。
   - 用 Adapter v2 的 create/send/wait/rebind/collect 执行和续接；幂等键、Worker ID、token、cursor、Run/Attempt/Lease 和锁写入 Runtime，不得伪造 running。
   - 默认使用用户可见 Worker；只有用户明确允许时使用内部 sub-agent。
   - 分发任务线程每 10 分钟增量检查 Runtime 中的 Worker 状态、Lease、最新里程碑；仅在触发条件出现时全文收口，不得再创建独立监控 Worker/任务。
   - 监控自身不可用时标记 `liveness_state=unknown`，保留 Attempt、Lease 所有权和资源锁；恢复后先 reconcile 原 Worker。只有 Provider 确认身份不可恢复且宽限复查失败才允许替换，避免重复分发。
   - `single-worker` 的新 Run 和 Gate 默认沿用原 `worker_id`；换 Worker 必须记录允许的 `worker_replacement_reason`，普通 Gate 切换、补测试或补 Evidence 不是替换理由。
   - 只有安全边界或受保护的冻结设计指纹变化时，取消当前 Attempt 并新建 Attempt；普通可恢复问题留在同一 Worker/Attempt 内修复。

5. **Verify and close**
   - 回收 commit、文件、命令、API、SQL、Browser、日志、质量检查和发布 Artifact；L0-L4 只能引用 Artifact ID。
   - Validator 自动校验 required/conditional/skipped 质量检查及 Artifact，再更新 Gate；非终态失败留在原 Attempt 修复。
   - 终态必须按 `references/closure.md` 主动报告状态、证据、缺口、用户动作、提交和唯一下一步。

## Commands

按相关 reference 运行面板、Resolver、协议一致性检查和 Validator。失败时修复 Task/Evidence/Runtime/Automation，或记录真实 Blocker；不得手工覆盖结论。

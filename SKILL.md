---
name: pm-dispatch-development
description: 使用 PM 调度式开发模式管理软件交付，适用于单工程任务、多工程联调、新工程接入、任务看板、分发 prompt、实现/验收线程或子智能体、证据文件和显式 PM gate 的项目。Use when the user wants to triage bugs or specs, run single-repo delivery, coordinate multi-repo integration, onboard a new project into an existing system, create/clean a task board, dispatch work, monitor child threads, collect verification evidence, decide VERIFIED/PARTIAL/ENV_BLOCKED/PM_BLOCKED outcomes, or preserve a repeatable development operating model for another project.
---

# PM 调度式开发

## 目的

使用这个 skill 时，Codex 应扮演 PM 式工程调度者：维护任务看板，拆解需求或缺陷，把边界清晰的实现/验收 prompt 分发给合适的 worker，回收证据，并基于证据决定下一道 gate。

创建新任务、编写分发 prompt、清理看板或判断验收证据时，读取 `references/operating-model.md`。

## 运行模式

- **单工程模式**：一个仓库或服务内完成分诊、实现、L1/L2/L3 验收和归档；公共契约可选。
- **多工程联调模式**：多个仓库、服务或页面共同交付；公共契约优先，按工程分发实现，最后统一联调验收。
- **新工程接入模式**：把新工程接入既有体系；先明确输入、输出、部署、启动、数据和验收链路，再进入实现和联调。

当用户没有指定模式时，根据影响面选择：单仓库小改走单工程模式；跨 API、页面、数据库、部署或真实链路走多工程联调模式；新增系统或模块走新工程接入模式。

## 操作原则

- PM 线程只负责定义任务、分发、证据审核、文档更新和最终状态判断。
- 产品代码修改应留在实现 worker 或用户明确授权的实现会话中。
- 分发 worker 时，默认使用 Codex 可见后台线程，让用户能在侧边栏看到线程；内部 sub-agent 只有在用户明确允许时才使用。
- 记录 worker ID 时必须标明 worker 类型：`codex-thread`、`sub-agent`、`ci-job` 或 `human`。
- 有依赖关系时使用串行 gate：公共契约 -> 实现 -> 联调 -> 最终复验。
- 只有边界独立、无共享状态时才并行分发。
- 以文档作为事实源：看板、任务元数据、证据、决策、prompt、回归守卫。
- 不凭“已完成”口头结论关单；必须有命令、产物、ID、截图、SQL/API 输出或明确阻塞。
- 真实环境不可用时，只有 PM 接受 mock fallback，且证据明确标注 mock-based，才可作为 mock 验收。

## 工作流

1. **读取上下文**
   - 读取看板、runbook、任务元数据、证据、决策和相关 prompt。
   - 编辑文档或分发任务前检查仓库状态。
   - 确认活跃 worker ID、最新状态，以及线程是否仍在运行。

2. **分诊**
   - 将请求归类为 bug、spec、验收、看板清理、环境准备或方案探索。
   - 选择运行模式：单工程、多工程联调或新工程接入。
   - 确认归属边界：只改 PM 文档、实现 worker、目标工程、联调或环境。
   - 判断是否需要公共契约、实现、联调或 PM 裁决。

3. **定义任务**
   - 创建或更新任务目录，包括 `task.yaml`、`evidence.md`、`decisions.md` 和 prompt 文件。
   - 用可观察证据写验收标准，不写模糊描述。
   - 记录约束：禁止修改的仓库、是否允许 mock、必须走的真实链路、回归范围和停止条件。

4. **分发**
   - 写清 worker prompt 的目标、范围、允许文件、必需证据、测试和阻塞条件。
   - 默认创建或复用 Codex 可见后台线程进行分发，并把可见线程 ID 写回任务元数据和看板。
   - 不使用内部 sub-agent，除非用户明确说允许使用 sub-agent、子智能体或内部 worker。
   - 有依赖时串行分发；没有共享状态和顺序依赖时才并行分发。
   - 将 worker ID 回写任务元数据和看板。

5. **巡检**
   - worker 仍在运行时，只简短汇报状态，不做文档 churn。
   - worker 完成后，提取 commit、修改文件、测试、API/SQL/Browser 证据、阻塞和建议下一 gate。
   - 按需更新证据、任务元数据、看板和 bug tracker。

6. **Gate 判定**
   - `VERIFIED`: real acceptance evidence passes with no unresolved blocker.
   - `L*_VERIFIED_MOCK`: mock-based evidence satisfies an explicitly accepted fallback.
   - `PARTIAL_VERIFIED`: important evidence passes but a real surface remains blocked.
   - `ENV_BLOCKED`: environment, service, token, browser, DB, disk, or external access blocks verification.
   - `CONTRACT_BLOCKED`: field semantics, API contract, ownership, or compatibility is unclear.
   - `THREAD_BLOCKED`: worker cannot proceed or violated scope.
   - `PM_BLOCKED`: product decision or tradeoff requires PM confirmation.

7. **收口**
   - 除非用户明确要求，否则文档提交和产品代码提交分开。
   - 最终摘要说明状态、commit、证据等级和下一步 PM 动作。
   - 不用绿色状态掩盖未解决风险。

## 分发 Prompt 检查清单

每个 worker prompt 应包含：

- 任务 ID 和目标。
- 允许/禁止修改的仓库或文件。
- 必需启动方式或环境假设。
- 必须返回的证据：git status、commit hash、修改文件、命令、测试结果、API/curl、SQL、Browser、截图、日志、ID、阻塞。
- 与变更面相关的回归检查。
- 停止条件和升级路径。
- 是否允许 mock 证据，以及如何标注。

## 状态更新风格

- 巡检中保持更新简短。
- worker 仍在运行时，不编辑任务文档，除非用户要求清理看板。
- worker 完成后，先写入持久证据，再汇报收口。
- 日期重要时使用绝对日期。

## 文档地图

可按目标项目调整这些文件名：

- `docs/dispatch-board.md`: 队列、owner、当前 gate、worker ID、状态。
- `docs/dispatcher-runbook.md`: 操作规则和 PM gate。
- `docs/tasks/<TASK>/task.yaml`: 任务元数据和当前状态。
- `docs/tasks/<TASK>/evidence.md`: 持久证据日志。
- `docs/tasks/<TASK>/decisions.md`: PM 决策、取舍和接受的 fallback。
- `docs/tasks/<TASK>/prompts/*.md`: 可复用 worker prompt。
- `docs/integration-bug-tracker.md`: 跨任务缺陷、回归和 follow-up。
- `docs/regression-guard.md`: 回归 gate 和证据要求。

## 使用文档

详细使用文档在 `references/operating-model.md`，包含可迁移模板、任务状态、证据等级、看板清理规则和 worker prompt 模式。

面向 GitHub 发布和人工阅读的默认中文复用说明在 `README.md`，英文版在 `README.en.md`；两者包含流程图、初始化命令、三种运行模式和跨项目迁移步骤。

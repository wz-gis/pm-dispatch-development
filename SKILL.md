---
name: pm-dispatch-development
description: 使用 PM 调度式开发模式管理软件交付，适用于单工程任务、多工程联调、新工程接入、任务看板、worker 分发、Run/Attempt/Lease、依赖与资源锁、结构化证据、自动 gate 校验和 VERIFIED/BLOCKED 收口的项目。
---

# PM 调度式开发

## 目的

使用这个 skill 时，Codex 应扮演 PM 式工程调度者：维护任务看板，拆解需求或缺陷，把边界清晰的实现/验收 prompt 分发给合适的 worker，回收结构化证据，并用 gate policy 校验结果推进下一道 gate。

创建新任务、编写分发 prompt、清理看板、判断验收证据或处理 worker 失联时，读取 `references/operating-model.md`。涉及机器校验时使用 `scripts/validate_pm_dispatch.py`，Schema 在 `references/schemas/`。

## 运行模式

- **单工程模式**：一个仓库或服务内完成分诊、实现、L1/L2/L3 验收和归档；公共契约可选。
- **多工程联调模式**：多个仓库、服务或页面共同交付；公共契约优先，按工程分发实现，最后统一联调验收。
- **新工程接入模式**：把新工程接入既有体系；先明确输入、输出、部署、启动、数据和验收链路，再进入实现和联调。

当用户没有指定模式时，根据影响面选择：单仓库小改走单工程模式；跨 API、页面、数据库、部署或真实链路走多工程联调模式；新增系统或模块走新工程接入模式。

## 分发策略

每个任务必须先选择 `dispatch.strategy`，避免把小任务机械分发成完整 PM 流程：

- **direct**：当前 PM 线程直接处理；适合单文件、小修、文案、配置、低风险文档或明确测试的小 bug。不创建 worker、run、lease、heartbeat。
- **single-worker**：一个 worker 同时完成实现和验证；适合单工程但需要 L1/L2/L3 证据的 UI/API 任务。
- **batch-worker**：一个 worker 处理 2-4 个同工程、同 owner、同 gate、同回归面的相似任务；共享 worker，不共享结论。
- **full-dispatch**：契约、实现、联调、收口分 gate；仅用于跨工程、DB/release、真实环境、高风险迁移或需要明确 PM gate 的任务。

默认偏向最轻可验证策略：能 direct 就 direct；direct 不足以拿到证据才 single-worker；多个相似任务才 batch-worker；只有高风险或跨边界任务才 full-dispatch。若 direct 过程中发现跨文件风险、缺真实链路、需要 Browser/API/SQL/release 证据或 owner 不清，必须升级策略并更新 `task.yaml.dispatch`。

## 状态模型

不要把所有状态塞进一个 `status` 字段。任务必须分成四条轨道：

- **Lifecycle**：任务在哪个交付阶段，例如 triage、contract、implementation、integration、verification、closure。
- **Verification**：需要哪些 L0-L4 证据、证据文件在哪里、当前证据是否足够。
- **Blocker**：环境、契约、worker、PM、依赖或资源锁阻塞，必须独立记录打开、解决或接受。
- **Closure**：PM 是否接受、是否归档、归档位置和关闭时间。

`task.yaml.status` 只保留对外摘要；真实判断必须同时读取 `lifecycle`、`verification`、`blockers`、`closure`、`runs`、`dependencies` 和 `resources`。

## 操作原则

- PM 线程只负责定义任务、分发、证据审核、文档更新和最终状态判断。
- 产品代码修改应留在实现 worker 或用户明确授权的实现会话中。
- `task.yaml` 和 `evidence.yaml` 必须符合 `references/schemas/task.schema.json` 与 `references/schemas/evidence.schema.json`；`evidence.md` 只作为人工阅读日志。
- 分发 worker 前必须先判断 `dispatch.strategy`；`direct` 任务不创建 worker、run、lease 或 heartbeat。
- 分发 worker 时，默认使用 Codex 可见后台线程，让用户能在侧边栏看到线程；内部 sub-agent 只有在用户明确允许时才使用。
- 不机械地一任务一线程；同工程、同 owner、同 gate、同回归面的相似 BUG / SPEC 应优先建议合并为一个批处理 worker。
- 合并只共享 worker，不合并任务状态；每个任务仍必须保留独立 task / evidence / decision、独立 gate 和独立阻塞结论。
- 每次分发必须创建或复用 `Run`；每次重试必须创建 `Attempt`；运行中的 attempt 必须持有未过期 `Lease`，否则不能继续视为活跃 worker。
- 记录 worker ID 时必须标明 worker 类型：`codex-thread`、`sub-agent`、`ci-job` 或 `human`。
- 分发可见 Codex worker 后，默认创建或更新 thread heartbeat 自动巡检；只有用户明确说不要轮询时才跳过。
- 自动巡检默认采用轻量模式：worker 运行中只读 worker 最新状态和必要的 lease 字段，不反复完整读取大文档；worker 完成、失败、失联、lease 临期或需要收口时才读取完整 PM 上下文。
- 看板和证据必须记录巡检 automation ID、频率、停止条件和是否采用轻量巡检。
- 有依赖关系时使用串行 gate：公共契约 -> 实现 -> 联调 -> 最终复验；依赖必须写入 `dependencies.requires`。
- 只有依赖图无未满足前置、资源锁无冲突、同 gate 无重复活跃 run 时才并行分发。
- 以文档作为事实源：看板、任务元数据、证据、决策、prompt、回归守卫。
- 不凭“已完成”口头结论关单；必须有命令、产物、ID、截图、SQL/API 输出或明确阻塞。
- 真实环境不可用时，只有 PM 接受 mock fallback，且证据明确标注 mock-based，才可作为 mock 验收。
- 证据必须匹配改动表面：页面改动要有 Browser 证据，接口改动要有 API 证据，SQL / release 改动要有升级或打包路径证据。
- 先验证用户原始路径和存量数据，再验证理想路径；不能用新造 happy path 掩盖旧工程、旧库或旧页面回退。
- 开发态、release 态、mock 态、真实链路必须分开标注；任一应测面缺失或 gate validator 未通过时，不得标记 `VERIFIED`。

## 工作流

1. **读取上下文**
   - 读取看板、runbook、任务元数据、`evidence.yaml`、`evidence.md`、决策和相关 prompt。
   - 编辑文档或分发任务前检查仓库状态。
   - 确认活跃 run、attempt、lease、worker ID、最新状态，以及线程是否仍在运行。

2. **分诊**
   - 将请求归类为 bug、spec、验收、看板清理、环境准备或方案探索。
   - 选择运行模式：单工程、多工程联调或新工程接入。
   - 选择分发策略：`direct`、`single-worker`、`batch-worker` 或 `full-dispatch`。
   - 确认归属边界：只改 PM 文档、实现 worker、目标工程、联调或环境。
   - 判断是否需要公共契约、实现、联调、依赖等待、资源锁或 PM 裁决。

3. **定义任务**
   - 创建或更新任务目录，包括 `task.yaml`、`evidence.yaml`、`evidence.md`、`decisions.md` 和 prompt 文件。
   - 用可观察证据写验收标准，不写模糊描述。
   - 记录 lifecycle、verification、blockers、closure、dispatch、dependencies、resources、runs。
   - 记录约束：禁止修改的仓库、是否允许 mock、必须走的真实链路、回归范围、资源锁和停止条件。
   - 为每个实现或联调任务写明最小回归矩阵：改动面、用户原始路径、启动形态、测试数据、L1/L2/L3/L4、存量数据回归和未覆盖项。

4. **分发**
   - 如果 `dispatch.strategy=direct`，当前线程直接处理并写入结构化证据；不得创建 worker、run、lease 或 heartbeat。
   - 如果 `dispatch.strategy=single-worker`，只创建一个实现+验证 worker；除非证据不足或阻塞升级，不再拆单独联调 worker。
   - 如果 `dispatch.strategy=batch-worker`，按批处理规则共享 worker，并逐任务保留 evidence / conclusion。
   - 如果 `dispatch.strategy=full-dispatch`，才执行契约 -> 实现 -> 联调 -> 收口的完整 gate。
   - 写清 worker prompt 的目标、范围、允许文件、必需证据、测试和阻塞条件。
   - 写清本轮必须验证的真实用户路径；UI 任务必须要求 Browser 点击证据，SQL / release 任务必须要求升级或打包路径证据，AI 任务必须要求成功路径证据。
   - 分发前检查依赖图、资源锁、同 gate 活跃 run 和 lease；存在冲突时不得并行分发。
   - 分发前判断能否合并：同一工程 / owner / gate / 启动方式 / 回归矩阵 / 资源锁兼容的任务优先批量分发；不同 gate、不同仓库 owner、高风险 release / SQL 或会拖慢 P0 的任务保持独立。
   - 使用批处理 worker 时，prompt 必须包含 `batchId`、任务清单、共享上下文、逐任务验收标准、逐任务停止条件和失败拆分规则。
   - 默认创建或复用 Codex 可见后台线程进行分发，并把 run、attempt、lease、worker ID 写回任务元数据和看板。
   - 不使用内部 sub-agent，除非用户明确说允许使用 sub-agent、子智能体或内部 worker。
   - 默认为可见 worker 创建或更新 heartbeat 自动巡检。一般任务默认每 15 分钟轮询一次、最多 6 次；只有短任务、P0 紧急验证或用户明确要求高频进度时，才使用每 5 分钟一次、最多 12 次。
   - 自动巡检 prompt 必须分成轻量运行中路径和完整收口路径：worker 仍在运行时只读取 worker 最新状态和必要 lease 字段，续租并汇报状态，不重读完整 specs / board / evidence / prompt，不做文档 churn；worker 完成、失败、失联或 lease 临期时再读取完整 PM 上下文，回收证据、更新 gate 并提交 PM 文档。
   - 有依赖时串行分发；没有共享状态和顺序依赖时才并行分发。
   - 批处理 worker 完成后逐任务判定；通过的任务可以归档，失败或证据不足的任务拆出返修，不得让一个任务的失败污染整批结论。
   - 将 run、attempt、lease、worker ID 和巡检 automation ID 回写任务元数据、看板或 evidence。

5. **巡检**
   - 优先依赖已登记的 heartbeat 自动巡检；用户询问状态时也可以立即手动读取 worker 线程。
   - worker 仍在运行且 lease 未过期时，采用轻量巡检：只读 worker 最新状态和必要 lease 字段，简短汇报状态并按需续租，不重读完整文档，不做文档 churn。
   - 如果用户要求在 PM 线程看到进度，运行中的 heartbeat 应使用 `NOTIFY` 简短汇报；否则可以保持安静巡检。
   - lease 过期或 worker 失联时，关闭当前 attempt 为 `expired`，释放资源锁，再决定重试或标记 `THREAD_BLOCKED`。
   - worker 完成后，提取 commit、修改文件、测试、API/SQL/Browser 证据、阻塞和建议下一 gate，写入 `evidence.yaml`。
   - 按需更新证据、任务元数据、看板和 bug tracker。
   - worker 完成并完成 PM 收口后，删除或暂停对应 heartbeat，避免重复巡检。

6. **Gate 判定**
   - `VERIFIED`: real acceptance evidence passes with no unresolved blocker.
   - `L*_VERIFIED_MOCK`: mock-based evidence satisfies an explicitly accepted fallback.
   - `PARTIAL_VERIFIED`: important evidence passes but a real surface remains blocked.
   - `ENV_BLOCKED`: environment, service, token, browser, DB, disk, or external access blocks verification.
   - `CONTRACT_BLOCKED`: field semantics, API contract, ownership, or compatibility is unclear.
   - `THREAD_BLOCKED`: worker cannot proceed or violated scope.
   - `PM_BLOCKED`: product decision or tradeoff requires PM confirmation.
   - 缺少应测 Browser、API、SQL、release、存量数据或真实链路证据时，不得提升到 `VERIFIED`；只能标记部分通过、环境阻塞、PM 阻塞或返修。
   - 提升到 verified-like 状态前必须运行 `python3 <skill>/scripts/validate_pm_dispatch.py docs/tasks/<TASK>/task.yaml`；失败项必须转成 blocker、返修 prompt 或 PM decision。

7. **收口**
   - 除非用户明确要求，否则文档提交和产品代码提交分开。
   - 最终摘要说明状态、commit、证据等级、validator 结果和下一步 PM 动作。
   - 不用绿色状态掩盖未解决风险。

## 分发 Prompt 检查清单

每个 worker prompt 应包含：

- 任务 ID 和目标。
- 允许/禁止修改的仓库或文件。
- 必需启动方式或环境假设。
- run ID、attempt ID、lease 到期时间和需要持有的资源锁。
- 必须返回的证据：git status、commit hash、修改文件、命令、测试结果、API/curl、SQL、Browser、截图、日志、ID、阻塞。
- 与变更面相关的回归检查。
- 用户原始路径、启动形态、测试数据和存量数据回归要求。
- 停止条件和升级路径。
- 是否允许 mock 证据，以及如何标注。
- 若是批处理 worker：`batchId`、任务 ID 列表、共享服务 / 数据、逐任务验收矩阵、逐任务 commit / 文件 / 测试映射、失败拆分规则。

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
- `docs/tasks/<TASK>/evidence.yaml`: 机器可校验的结构化证据。
- `docs/tasks/<TASK>/evidence.md`: 持久证据日志。
- `docs/tasks/<TASK>/decisions.md`: PM 决策、取舍和接受的 fallback。
- `docs/tasks/<TASK>/prompts/*.md`: 可复用 worker prompt。
- `docs/integration-bug-tracker.md`: 跨任务缺陷、回归和 follow-up。
- `docs/regression-guard.md`: 回归 gate 和证据要求。
- `references/schemas/task.schema.json`: `task.yaml` 的正式 Schema。
- `references/schemas/evidence.schema.json`: `evidence.yaml` 的正式 Schema。
- `scripts/validate_pm_dispatch.py`: Schema、gate policy、依赖图、资源锁和 lease 校验脚本。

## 使用文档

详细使用文档在 `references/operating-model.md`，包含可迁移模板、任务状态、证据等级、看板清理规则和 worker prompt 模式。

面向 GitHub 发布和人工阅读的默认中文复用说明在 `README.md`，英文版在 `README.en.md`；两者包含流程图、初始化命令、三种运行模式和跨项目迁移步骤。

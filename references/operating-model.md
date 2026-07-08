# PM 调度式开发使用文档

这份文档用于把“PM 看板 + 分发 worker + 证据回收 + gate 判定 + 文档归档”的开发模式迁移到其它项目。当前模型把任务拆成 lifecycle、verification、blocker、closure 四条状态轨道，并用 `task.yaml`、`evidence.yaml`、Run/Attempt/Lease、依赖图、资源锁和 gate validator 保证调度可恢复、可并行、可验收。

## 1. 任务状态模型

Bug 和 Spec 不再只依赖一个状态字段。`task.yaml.status` 是看板摘要，真实推进必须同时读取四条轨道：

1. `lifecycle`：任务所在交付阶段，负责说明下一步应该分诊、契约、实现、联调、验收还是归档。
2. `verification`：证据要求和证据状态，负责说明必须覆盖哪些 L0-L4、证据文件位置和缺口。
3. `blockers`：阻塞事实，负责说明环境、契约、worker、PM、依赖或资源锁是否阻塞推进。
4. `closure`：收口事实，负责说明 PM 是否接受、是否关闭、是否归档。

Lifecycle 推荐阶段：

1. `NEW`：请求已捕获，尚未分析。
2. `TRIAGED`：owner、影响面、优先级和验收标准已明确。
3. `CONTRACT`：正在定义公共字段、API、页面行为或跨系统语义。
4. `READY_FOR_IMPL`：PM 已确认可实施方案。
5. `IN_IMPL`：实现 worker 正在执行。
6. `READY_FOR_INTEGRATION`：实现证据足够，可以进入联调验收。
7. `IN_INTEGRATION`：真实或 PM 接受的 mock 联调正在执行。
8. `VERIFIED`、`PARTIAL_VERIFIED`、`ENV_BLOCKED`、`CONTRACT_BLOCKED`、`THREAD_BLOCKED` 或 `PM_BLOCKED`。

只有当前 gate 的结构化证据已经写入 `evidence.yaml`，并且 gate validator 通过或产生明确 blocker，才能推进任务状态。`evidence.md` 可以保留人类可读叙述，但不得作为唯一证据源。

## 2. 运行模式

### 单工程模式

适用于一个仓库、一个服务或一个页面内能闭环的问题。公共契约可选，流程通常是：

```text
TRIAGED -> READY_FOR_IMPL -> IN_IMPL -> READY_FOR_INTEGRATION -> IN_INTEGRATION -> VERIFIED
```

使用要求：

- 在 `task.yaml.area` 写清唯一工程或模块。
- 实现 Worker 和联调 Worker 可以是同一个执行者，但证据仍要分开写。
- 至少保留 L1 测试或构建证据；用户可见行为需要 L3。
- 不需要为每个小改强制创建公共契约 prompt。

常用触发语：

```text
使用 $pm-dispatch-development 以单工程模式处理这个 bug，只需要实现和 L3 验收。
```

### 多工程联调模式

适用于多个仓库、服务、页面、数据库或外部环境共同交付的任务。公共契约应作为前置 gate，流程通常是：

```text
TRIAGED -> CONTRACT -> READY_FOR_IMPL -> 多工程 IN_IMPL -> READY_FOR_INTEGRATION -> IN_INTEGRATION -> VERIFIED/PARTIAL/ENV_BLOCKED
```

使用要求：

- 在 `task.yaml.area` 列出所有工程，例如 `frontend`、`backend`、`worker`、`database`。
- 每个工程可以有独立实现 Worker；共享字段、API、状态机和页面行为必须先在契约中固定。
- 联调 Worker 统一验证跨工程链路，必须记录服务启动方式、端口、PID、日志路径、测试数据、API/SQL/Browser、关键 ID 和阻塞项。
- 任何真实环境不可用的 fallback 都必须由 PM 接受，并在 `evidence.yaml.conclusion.accepted_fallback` 与 `evidence.md` 同时标注 `mock-based`。

常用触发语：

```text
使用 $pm-dispatch-development 以多工程联调模式处理这个需求，先做公共契约，再分别分发前端和后端实现，最后统一联调验收。
```

### 新工程接入模式

适用于把新系统、新模块或外部工程接入已有交付体系。它比普通多工程联调多一个接入核对层：

```text
NEW -> TRIAGED -> CONTRACT -> 接入核对 -> READY_FOR_IMPL -> IN_IMPL -> IN_INTEGRATION
```

接入核对至少包括：

- 工程来源、仓库地址、分支和 owner。
- 启动命令、运行端口、健康检查、日志路径。
- 输入输出契约、鉴权、配置、数据库和外部依赖。
- 测试数据准备方式，真实数据不可用时的 mock fallback。
- 最小 L0/L1/L2/L3 验收门槛。

常用触发语：

```text
使用 $pm-dispatch-development 接入一个新工程，创建接入任务、契约任务、实现任务和联调验收任务。
```

## 2.1 分发策略

每个任务必须在 `task.yaml.dispatch.strategy` 记录分发策略。策略选择先于 worker 创建，目标是用最轻可验证方式完成任务。

| Strategy | 何时使用 | Worker / Run | Heartbeat |
| --- | --- | --- | --- |
| `direct` | 单文件、小修、文案、配置、低风险文档、明确测试的小 bug | 不创建 | 不创建 |
| `single-worker` | 单工程但需要实现 + L1/L2/L3 验证 | 一个实现+验证 worker | 可选，默认轻量 |
| `batch-worker` | 2-4 个同工程、同 owner、同 gate、同回归面的任务 | 一个批处理 worker，共享 run | 可选，默认轻量 |
| `full-dispatch` | 跨工程、DB/release、真实环境、高风险迁移、契约不清 | 契约/实现/联调分 gate | 默认创建 |

选择规则：

- 默认从 `direct` 开始判断；能在当前线程完成且证据可观察，就不要分发 worker。
- direct 不能取得应测证据、需要 Browser/API/SQL/release 验收或实现上下文过大时，升级为 `single-worker`。
- 多个相似任务满足合并条件时，用 `batch-worker`，但每个任务仍保留独立 evidence 和 conclusion。
- 只有跨边界、高风险或必须 PM gate 串行确认时，才用 `full-dispatch`。
- 策略升级必须更新 `task.yaml.dispatch.reason` 和 `escalation_triggers`；策略降级必须说明为什么不再需要 worker。

## 3. 证据等级

- `L0`：静态检查、文档核对、契约 grep、schema 检查。
- `L1`：单测、组件测试、本地编译或构建。
- `L2`：API、curl、SQL、服务级验证。
- `L3`：Browser、页面或人工工作流验证。
- `L4`：真实端到端链路验证。
- `L*_VERIFIED_MOCK`：同等级证据，但因为真实条件不可用，且 PM 接受 mock fallback。

证据等级和任务结论不要混用。例如：`PARTIAL_VERIFIED / L2_VERIFIED` 表示接口通过，但 Browser 或真实环境仍阻塞。

### 3.1 回归放行红线

使用这个模式时，PM gate 只认可与改动表面一致的证据。

- 页面、按钮、tab、弹框、表格或路由改动：必须有 Browser 点击证据；API、SQL、静态检查只能作为辅助。
- API、DTO、状态机、异步任务改动：必须有 curl / API / 任务 ID / 状态流转证据。
- SQL、表结构、迁移、启动脚本、打包脚本或 release 静态资源改动：必须有旧库或现有库升级路径、打包路径或 release 启动证据。
- AI 功能：必须验证真实 provider 或 PM 接受的可控 provider 成功返回，并继续验证后续 dry-run / 保存 / 启用 / 展示中的适用链路；只验证失败降级不算通过。
- 核心业务链路：必须先验证用户反馈的原始路径，再验证修复后的理想路径。
- 存量数据：涉及扫描、索引、日志、规则或报告时，必须抽查既有工程、旧任务、latestSuccess / PARTIAL_SUCCESS 或历史数据不回退。
- 环境形态：dev server、jar 内置静态资源、release 包、mock 数据、真实链路必须分别标注，不能混用结论。

每个实现或联调 evidence 至少包含：

```text
改动面：
用户原始路径：
启动形态：dev / jar / release / mock / real
测试数据：projectId / taskId / snapshotId / 文件 / 日志 / 用户输入
L1：
L2：
L3：
L4：
存量数据回归：
未覆盖项：
结论：
```

如果矩阵中的应测项没有覆盖，结论不能写 `VERIFIED`。应选择 `PARTIAL_VERIFIED`、`ENV_BLOCKED`、`PM_BLOCKED`，或生成返修 prompt。

### 3.2 结构化证据

每个任务必须有两个证据文件：

- `evidence.yaml`：机器可校验事实源，必须符合 `references/schemas/evidence.schema.json`。
- `evidence.md`：面向 PM 的叙述日志，记录上下文、摘要和人工判断。

`evidence.yaml` 至少记录：

- `verification.changed_surface`：改动面，例如 `ui`、`api`、`sql`、`release`。
- `verification.original_user_path`：用户反馈的原始路径。
- `verification.runtime_shape`：`dev`、`jar`、`release`、`mock` 或 `real`。
- `verification.levels.L0-L4`：每级证据的 `status`、摘要、命令和引用。
- `artifacts`：commands、commits、files_changed、api、sql、browser、screenshots、logs、ids、upgrade_path、release_path。
- `runs`：产生证据的 run、attempt、worker 和 commit。
- `blockers`：本轮仍未解决或已接受的阻塞。
- `conclusion`：最终状态、最高证据等级、是否 mock、真实链路是否通过、PM 接受的 fallback。

提升 gate 前运行：

```bash
python3 ~/.codex/skills/pm-dispatch-development/scripts/validate_pm_dispatch.py docs/tasks/<TASK>/task.yaml
```

## 4. 任务目录

最小任务目录：

```text
docs/tasks/BUG-000/
├── task.yaml
├── evidence.yaml
├── evidence.md
├── decisions.md
└── prompts/
    ├── 01-contract.md
    ├── 02-implementation.md
    └── 03-integration.md
```

`task.yaml` 必须符合 `references/schemas/task.schema.json`。推荐骨架：

```yaml
id: BUG-000
title: 简短标题
type: bug
priority: P0
status: TRIAGED
mode: multi-project-integration
area:
  - frontend
  - backend
lifecycle:
  phase: triage
  owner: PM
  accepted_scope: null
  next_action: define contract
  updated_at: 2026-07-01T00:00:00Z
verification:
  required_levels: [L1, L2, L3]
  gate_policy: default
  evidence_file: evidence.yaml
  status: PENDING
  mock_allowed: false
  missing: []
blockers: []
closure:
  status: open
  accepted_by: null
  accepted_at: null
  closed_at: null
  archived_to: null
  notes: null
dependencies:
  requires: []
  blocks: []
  graph_checked_at: null
resources:
  locks: []
dispatch:
  strategy: direct
  reason: Small, low-risk task that can be handled in the PM thread.
  worker_required: false
  heartbeat_required: false
  selected_at: 2026-07-01T00:00:00Z
  max_parallel_workers: null
  escalation_triggers:
    - Requires Browser/API/SQL/release evidence.
    - Scope crosses owner or repository boundary.
runs: []
last_updated: 2026-07-01
```

向后兼容：旧任务可以保留 `evidence.md` 和历史 `threads` 字段作为人工线索，但新任务必须使用 `runs` 记录 worker。

`evidence.md` 推荐结构：

```markdown
# Evidence

## 2026-07-01 PM 分诊

- 需求：
- 范围：
- 验收：
- 阻塞：

## Worker 证据

- 线程：
- Commit：
- 修改文件：
- 命令：
- API/SQL/Browser：
- 结论：
```

`decisions.md` 推荐结构：

```markdown
# Decisions

## 2026-07-01 PM 决策

- 决策：
- 原因：
- 接受的 fallback：
- 禁止事项：
- 后续：
```

`mode` 推荐值：

- `single-project`
- `multi-project-integration`
- `new-project-onboarding`

## 5. 看板模板

看板行保持紧凑，突出状态和下一步：

```markdown
| ID | Priority | Status | Evidence | Owner | Next |
| --- | --- | --- | --- | --- | --- |
| BUG-000 | P0 | IN_IMPL | L1 pending | Backend worker | 等待实现证据 |
```

看板清理规则：

- 已终态任务折叠到 verified/archive 区。
- 活跃任务放在顶部。
- worker ID 只有在证据已保存后才能移除。
- 不删除阻塞记录；已解决阻塞移动到 evidence。

### Worker 可见性规则

- 默认 worker 类型是 `codex-thread`：使用 Codex 可见后台线程分发，让用户能在侧边栏看到并打开。
- 内部 `sub-agent` 只能在用户明确允许使用 sub-agent、子智能体或内部 worker 时使用。
- 看板和 `task.yaml.runs[].worker_id` 必须记录 worker ID，并标明 worker 类型，例如 `codex-thread:<thread-id>` 或 `sub-agent:<agent-id>`。
- 如果旧 worker 是不可见 sub-agent 且用户没有明确授权，应标记 `THREAD_BLOCKED` 或重新分发到可见 Codex 线程。

### Run / Attempt / Lease

- `Run`：一次 gate 分发单元，例如 BUG-001 的 implementation run。
- `Attempt`：Run 的一次具体尝试；重试、返修或 worker 失联后重新分发都必须新建 attempt。
- `Lease`：运行中 attempt 的租约，包含 holder、acquired_at、heartbeat_at、expires_at、renew_count。

分发规则：

- `dispatch.strategy=direct` 时不得创建 active run、attempt、lease 或 heartbeat；只更新 task/evidence/decisions。
- 同一任务、同一 gate 默认只能有一个 `queued` 或 `running` run，除非 run 显式 `allow_parallel: true` 且资源锁兼容。
- 分发前必须检查是否已有未过期 lease；有则复用或等待，不得重复分发。
- heartbeat 看到 worker 仍在运行时，默认走轻量巡检：只读 worker 最新状态和必要 lease 字段，续租 lease 和汇报状态，不重读完整 PM 文档，不做文档 churn。
- lease 到期且 worker 无回应时，把 attempt 标记 `expired`，释放资源锁，再选择重试、返修或 `THREAD_BLOCKED`。
- worker 完成后，把 attempt 标记 `succeeded`、`failed` 或 `blocked`，写入 commit 和 evidence_ref。

### 依赖图与资源锁

依赖写入 `task.yaml.dependencies`：

- `requires`：当前任务开始某阶段前必须满足的任务和状态。
- `blocks`：当前任务完成后可解锁的下游任务。
- `graph_checked_at`：最近一次检查时间。

资源锁写入 `task.yaml.resources.locks`：

- 对会冲突的 repo、branch、database、port、release package、真实环境账号、migration window 使用 `exclusive`。
- 对可并行读取的文档、只读 API、共享 fixtures 使用 `shared`。
- exclusive lock 与任何其它 active lock 冲突；shared lock 只与 exclusive lock 冲突。
- 锁必须绑定 holder_run_id 和 lease_expires_at；lease 过期后锁不得继续阻塞其它任务。

批量或并行分发前运行 validator 的 `--tasks-dir` 模式检查全局依赖和锁：

```bash
python3 ~/.codex/skills/pm-dispatch-development/scripts/validate_pm_dispatch.py --tasks-dir docs/tasks
```

### 任务合并与批处理 Worker

默认先判断能否合并相似任务，避免每个 BUG / SPEC 都创建独立线程。

可以合并：

- 同一工程、同一 owner、同一代码区域或同一页面 / API / 表。
- 同一 gate，例如都在实现、都在联调或都在环境复验。
- 启动方式、测试数据和回归矩阵可复用。
- 依赖图无未满足前置，资源锁兼容。
- 一个 commit 或一组测试可以清晰映射到多个任务。
- 任一任务失败时，可以拆出独立返修，不影响其它任务归档。

禁止合并：

- 一个任务仍需公共契约或 PM 裁决，另一个已可实施。
- 不同仓库 owner、不同工作树、不同 release 节奏或互相冲突的 commit 范围。
- 破坏性 SQL、release 打包、真实生产链路、高风险迁移与普通页面 / API 修复混在一起。
- P0 紧急故障会被低优先级任务拖慢。
- 需要同一个 exclusive resource，例如同一 DB migration、同一 release 包、同一端口或同一真实账号。
- 合并后无法逐任务记录证据、状态、未覆盖项和阻塞原因。

批处理规则：

- 每个任务仍有独立 `task.yaml`、`evidence.yaml`、`evidence.md`、`decisions.md`。
- 批处理 worker 可以共享 run，但每个任务必须保留独立 evidence 和 conclusion。
- 看板可多个任务指向同一 `batch-worker:<thread-id>`。
- 默认批量规模 2-4 个任务；超过 5 个需要 PM 确认。
- worker prompt 必须包含 `batchId`、任务清单、共享上下文、逐任务验收标准、逐任务停止条件和失败拆分规则。
- heartbeat 可以共用一个 automation，但完成后必须逐任务更新状态。
- 一个 commit 可以覆盖多个任务，但 evidence 必须写清任务 ID、修改文件、测试和验证证据的映射关系。

### 自动巡检规则

- 分发 `codex-thread` worker 后，默认创建或更新 thread heartbeat 自动巡检；只有用户明确说不要轮询时才跳过。
- 一般任务默认频率：每 15 分钟一次，最多 6 次；只有短任务、P0 紧急验证或用户明确要求高频进度时，才使用每 5 分钟一次、最多 12 次。
- 自动巡检必须记录到看板或 evidence：automation ID、目标 worker ID、频率、停止条件，以及是否采用轻量巡检。
- 自动巡检 prompt 必须区分轻量运行中路径和完整收口路径：
  - 运行中：只读取 worker 线程最新状态；如需确认 lease，只读取 `task.yaml` 的 runs/lease 相关字段。
  - 完成 / 失败 / 失联 / lease 临期：读取完整 board/runbook/task/evidence.yaml/evidence.md/decisions/current prompt，再做证据回收和 gate 判定。
- worker 仍在运行时：只续租 lease 并中文简短汇报当前进展，不重读完整 specs / board / evidence / prompt，不更新其它文档，不提交。
- 如果用户要求在 PM 线程看到进度，运行中的 heartbeat 应使用 `NOTIFY` 简短汇报；否则可以保持安静巡检。
- worker 失联或 lease 过期时：标记 attempt expired，释放资源锁，再决定重试或 THREAD_BLOCKED。
- worker 完成时：回收 commit、files、tests、API/SQL/Browser、端口、日志、阻塞和 gate 建议；更新 evidence.yaml、evidence.md、task.yaml、dispatch-board、bug tracker；运行 gate validator 后提交 PM 文档。
- PM 收口后删除或暂停 heartbeat，避免对已归档任务重复巡检。

## 6. Worker Prompt 模板

```markdown
你正在处理 <TASK-ID>。

调度身份：
- run_id：
- attempt_id：
- worker_type：
- worker_id：
- lease_expires_at：
- resource_locks：

批处理信息（如适用）：
- batchId：
- 任务清单：
- 共享上下文：
- 逐任务验收标准：
- 失败拆分规则：

目标：
- <一个清晰目标>

允许范围：
- 可以修改 <repo/files>。
- 不要修改 <forbidden repos/files>。

必读上下文：
- 读取 <docs>。
- 遵守 <contract/runbook>。

实现要求：
- <requirements>

验证要求：
- 返回 git status。
- 如有代码变更，返回 commit hash。
- 列出修改文件。
- 执行 <commands>。
- 提供 API/curl/SQL/Browser 证据。
- 提供可写入 evidence.yaml 的结构化摘要。
- 按回归矩阵说明用户原始路径、启动形态、测试数据、存量数据回归和未覆盖项。
- 明确说明阻塞项。

停止条件：
- 如果 <condition>，标记 CONTRACT_BLOCKED / ENV_BLOCKED / THREAD_BLOCKED 并停止。
```

多工程联调 Worker 还应补充：

```markdown
工程矩阵：
- <工程 A>：启动方式、端口、owner、commit、日志路径。
- <工程 B>：启动方式、端口、owner、commit、日志路径。

跨工程验收链路：
- 输入：
- 调用链：
- 输出：
- 关键 ID：
- 回归项：
```

新工程接入 Worker 还应补充：

```markdown
接入核对：
- 仓库/分支：
- 启动命令：
- 健康检查：
- 配置/密钥：
- 数据库/外部依赖：
- 最小验收路径：
```

## 7. 巡检 Heartbeat 模板

```markdown
轻量巡检 <TASK-ID> 的可见 worker。
默认只读取 worker 线程 <ID> 最新状态；如需确认 lease，仅读取 task.yaml 的 runs/lease 相关字段。
如果线程仍在运行且 lease 未过期，只简短汇报当前进展，按需续租 lease，不重读完整 PM 文档，不改其它文档，不提交。
如果 lease 距离过期不足 30 分钟，只更新必要 lease 字段并说明。
如果 worker 完成、失败、失联或 lease 过期，再读取 board、runbook、task.yaml、evidence.yaml、evidence.md、decisions.md 和当前 prompt。
完整收口时提取 commit/files/tests/API/SQL/Browser/evidence/blockers，
更新 evidence.yaml、任务证据、任务状态、看板和 bug tracker，运行 gate validator，并提交 docs。
收口后删除或暂停本 heartbeat。
```

## 8. Gate 判定

- `VERIFIED`：真实验收路径通过，无未解决阻塞。
- `L*_VERIFIED_MOCK`：PM 接受 mock fallback，且证据明确标注。
- `PARTIAL_VERIFIED`：部分关键面通过，但不足以 verified。
- `ENV_BLOCKED`：token、DB、服务、Browser、磁盘、真实日志、网络或外部系统阻塞。
- `CONTRACT_BLOCKED`：公共语义或归属不清。
- `THREAD_BLOCKED`：worker 越界、反复失败或无法推进。
- `PM_BLOCKED`：产品行为、风险或取舍需要 PM 决定。

Gate policy 必须自动校验：

- Schema：`task.yaml` 和 `evidence.yaml` 字段完整、枚举合法。
- Run/Lease：运行中 run 必须有未过期 lease，同 gate 不得重复活跃分发。
- Dependency：已进入实现、联调或收口的任务必须满足 `dependencies.requires`。
- Resource lock：exclusive lock 不得与其它 active lock 并存。
- Evidence：required L0-L4 必须 pass 或 pass_mock；mock 必须有 accepted_fallback。
- Surface：UI/L3 要 Browser，API/L2 要 API/curl/SQL/command，SQL/release 要 upgrade_path 或 release_path。
- Blocker：open blocker 存在时不得 verified-like。

Validator 失败时只能选择三种动作：补证据、生成返修 prompt、或记录 blocker / PM decision。

## 9. PM 评审问题

实施分发前，如仍有歧义，先问：

- 当前任务是单工程、多工程联调，还是新工程接入？
- 当前任务能否 direct 完成？如果不能，为什么需要 single-worker、batch-worker 或 full-dispatch？
- 用户可见验收行为是什么？
- 哪个仓库拥有修复？
- 如果是多工程联调，跨工程字段、API、状态和启动顺序是什么？
- 如果是新工程接入，最小健康检查和最小验收链路是什么？
- 真实日志或真实环境不可用时，是否接受 mock 证据？
- 是否需要更新公共契约？
- 是否有未满足依赖或会冲突的资源锁？
- 哪些回归任务必须保持通过？
- 如果 worker 证明原方案不安全，应如何停止或升级？

## 10. 反模式

- worker 说完成就直接标记 verified，没有证据。
- PM 文档提交混入无关生成物。
- 验收 worker 静默修改产品代码。
- 多工程联调没有公共契约，直接让各工程分别猜字段。
- 新工程接入没有启动、健康检查和最小验收路径。
- 契约要求 ingestion/indexing 修复，却用 query 层兜底绕过。
- 把 mock 证据当真实证据。
- 用 API / SQL 通过替代页面点击通过。
- 用源码 dev server 通过替代 jar 内置静态资源或 release 包通过。
- 用新造数据通过替代存量工程 / 存量任务回归。
- AI 只测失败降级，不测成功草案和后续链路。
- 旧库升级、SQL update、打包脚本、启动脚本没有被真实执行。
- 使用旧截图或旧 curl 输出，却没有日期、ID 或命令。
- 不保存中间证据，一次跳过多个 gate。
- 不检查 lease 就重复分发同一 gate。
- 不声明资源锁就并行跑会冲突的 DB、端口、release 或真实账号任务。
- validator 失败但仍人工标绿。
- 小型单文件任务默认 full-dispatch，制造无意义 worker / heartbeat / lease 开销。
- single-worker 足够完成实现和验证时，仍拆成实现 worker + 联调 worker。

## 11. 跨项目落地清单

在新项目使用此模式：

1. 创建 `docs/dispatch-board.md`。
2. 创建 `docs/dispatcher-runbook.md`。
3. 创建 `docs/tasks/<TASK>/` 目录。
4. 按 schema 创建 `task.yaml` 和 `evidence.yaml`。
5. 定义证据等级、gate policy 和终态。
6. 定义分发策略：`direct`、`single-worker`、`batch-worker`、`full-dispatch`。
7. 定义 PM 线程允许修改哪些仓库。
8. 默认把 worker 分发到 Codex 可见后台线程；只有用户明确授权时才使用内部 sub-agent。
9. 为可见 worker 创建轻量 heartbeat 自动巡检，并记录 automation ID、频率、停止条件和轻量巡检策略。
10. 定义 worker 是 `codex-thread`、`sub-agent`、`ci-job` 还是 `human`。
11. 每次 worker 分发写入 Run/Attempt/Lease；direct 任务不得创建 active run。
12. 为并行任务声明 dependencies 和 resources.locks。
13. 要求 worker prompt 返回 commit hash、修改文件、命令和阻塞项。
14. 每个 gate 要求提交文档更新，并运行 `scripts/validate_pm_dispatch.py`。
15. 为跨任务承诺增加 regression guard。
16. 每天清理看板并归档终态任务，收口后删除或暂停对应 heartbeat。

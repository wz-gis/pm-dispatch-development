# PM 调度式开发使用文档

这份文档用于把“PM 看板 + 分发 worker + 证据回收 + gate 判定 + 文档归档”的开发模式迁移到其它项目。

## 1. 任务生命周期

Bug 和 Spec 都使用同一套生命周期：

1. `NEW`：请求已捕获，尚未分析。
2. `TRIAGED`：owner、影响面、优先级和验收标准已明确。
3. `CONTRACT`：正在定义公共字段、API、页面行为或跨系统语义。
4. `READY_FOR_IMPL`：PM 已确认可实施方案。
5. `IN_IMPL`：实现 worker 正在执行。
6. `READY_FOR_INTEGRATION`：实现证据足够，可以进入联调验收。
7. `IN_INTEGRATION`：真实或 PM 接受的 mock 联调正在执行。
8. `VERIFIED`、`PARTIAL_VERIFIED`、`ENV_BLOCKED`、`CONTRACT_BLOCKED`、`THREAD_BLOCKED` 或 `PM_BLOCKED`。

只有当前 gate 的证据已经写入文档，才能推进任务状态。

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
- 任何真实环境不可用的 fallback 都必须由 PM 接受，并在 `evidence.md` 标注 `mock-based`。

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

## 4. 任务目录

最小任务目录：

```text
docs/tasks/BUG-000/
├── task.yaml
├── evidence.md
├── decisions.md
└── prompts/
    ├── 01-contract.md
    ├── 02-implementation.md
    └── 03-integration.md
```

`task.yaml` 推荐字段：

```yaml
id: BUG-000
title: 简短标题
priority: P0
status: TRIAGED
evidence_level: NONE
owner: PM
area:
  - frontend
  - backend
mode: multi-project-integration
threads:
  contract: null
  implementation: null
  integration: null
blockers: []
last_updated: 2026-07-01
```

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
- 看板和 `task.yaml.threads` 必须记录 worker ID，并标明 worker 类型，例如 `codex-thread:<thread-id>` 或 `sub-agent:<agent-id>`。
- 如果旧 worker 是不可见 sub-agent 且用户没有明确授权，应标记 `THREAD_BLOCKED` 或重新分发到可见 Codex 线程。

### 任务合并与批处理 Worker

默认先判断能否合并相似任务，避免每个 BUG / SPEC 都创建独立线程。

可以合并：

- 同一工程、同一 owner、同一代码区域或同一页面 / API / 表。
- 同一 gate，例如都在实现、都在联调或都在环境复验。
- 启动方式、测试数据和回归矩阵可复用。
- 一个 commit 或一组测试可以清晰映射到多个任务。
- 任一任务失败时，可以拆出独立返修，不影响其它任务归档。

禁止合并：

- 一个任务仍需公共契约或 PM 裁决，另一个已可实施。
- 不同仓库 owner、不同工作树、不同 release 节奏或互相冲突的 commit 范围。
- 破坏性 SQL、release 打包、真实生产链路、高风险迁移与普通页面 / API 修复混在一起。
- P0 紧急故障会被低优先级任务拖慢。
- 合并后无法逐任务记录证据、状态、未覆盖项和阻塞原因。

批处理规则：

- 每个任务仍有独立 `task.yaml`、`evidence.md`、`decisions.md`。
- 看板可多个任务指向同一 `batch-worker:<thread-id>`。
- 默认批量规模 2-4 个任务；超过 5 个需要 PM 确认。
- worker prompt 必须包含 `batchId`、任务清单、共享上下文、逐任务验收标准、逐任务停止条件和失败拆分规则。
- heartbeat 可以共用一个 automation，但完成后必须逐任务更新状态。
- 一个 commit 可以覆盖多个任务，但 evidence 必须写清任务 ID、修改文件、测试和验证证据的映射关系。

### 自动巡检规则

- 分发 `codex-thread` worker 后，默认创建或更新 thread heartbeat 自动巡检；只有用户明确说不要轮询时才跳过。
- 短任务默认频率：每 5 分钟一次，最多 12 次；更长任务可以降低频率或改为人工 checkpoint。
- 自动巡检必须记录到看板或 evidence：automation ID、目标 worker ID、频率、停止条件。
- 自动巡检 prompt 必须包含：读取 board/runbook/task/evidence/decisions/current prompt，读取 worker 线程状态，区分运行中和已完成。
- worker 仍在运行时：只中文简短汇报当前进展，不更新文档，不提交。
- worker 完成时：回收 commit、files、tests、API/SQL/Browser、端口、日志、阻塞和 gate 建议；更新 evidence、task.yaml、dispatch-board、bug tracker；运行文档校验后提交 PM 文档。
- PM 收口后删除或暂停 heartbeat，避免对已归档任务重复巡检。

## 6. Worker Prompt 模板

```markdown
你正在处理 <TASK-ID>。

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
继续 <TASK-ID> 自动调度巡检。
先读取 board、runbook、task.yaml、evidence.md、decisions.md 和当前 prompt。
读取 worker 线程 <ID> 最新状态。
如果线程仍在运行，只简短更新状态，不改文档。
如果线程完成，提取 commit/files/tests/API/SQL/Browser/evidence/blockers，
更新任务证据、任务状态、看板和 bug tracker，并提交 docs。
收口后删除或暂停本 heartbeat。
```

## 8. Gate 判定

- `VERIFIED`：真实验收路径通过，无未解决阻塞。
- `L3_VERIFIED`：页面工作流通过，但不要求完整 L4。
- `L4_VERIFIED`：真实端到端链路通过。
- `L*_VERIFIED_MOCK`：PM 接受 mock fallback，且证据明确标注。
- `PARTIAL_VERIFIED`：部分关键面通过，但不足以 verified。
- `ENV_BLOCKED`：token、DB、服务、Browser、磁盘、真实日志、网络或外部系统阻塞。
- `CONTRACT_BLOCKED`：公共语义或归属不清。
- `THREAD_BLOCKED`：worker 越界、反复失败或无法推进。
- `PM_BLOCKED`：产品行为、风险或取舍需要 PM 决定。

## 9. PM 评审问题

实施分发前，如仍有歧义，先问：

- 当前任务是单工程、多工程联调，还是新工程接入？
- 用户可见验收行为是什么？
- 哪个仓库拥有修复？
- 如果是多工程联调，跨工程字段、API、状态和启动顺序是什么？
- 如果是新工程接入，最小健康检查和最小验收链路是什么？
- 真实日志或真实环境不可用时，是否接受 mock 证据？
- 是否需要更新公共契约？
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

## 11. 跨项目落地清单

在新项目使用此模式：

1. 创建 `docs/dispatch-board.md`。
2. 创建 `docs/dispatcher-runbook.md`。
3. 创建 `docs/tasks/<TASK>/` 目录。
4. 定义证据等级和终态。
5. 定义 PM 线程允许修改哪些仓库。
6. 默认把 worker 分发到 Codex 可见后台线程；只有用户明确授权时才使用内部 sub-agent。
7. 为可见 worker 创建 heartbeat 自动巡检，并记录 automation ID、频率和停止条件。
8. 定义 worker 是 `codex-thread`、`sub-agent`、`ci-job` 还是 `human`。
9. 要求 worker prompt 返回 commit hash、修改文件、命令和阻塞项。
10. 每个 gate 要求提交文档更新。
11. 为跨任务承诺增加 regression guard。
12. 每天清理看板并归档终态任务，收口后删除或暂停对应 heartbeat。

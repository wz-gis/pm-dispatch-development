---
name: pm-dispatch-development
description: Use when managing software delivery through PM task boards, worker dispatch, Run/Attempt/Lease recovery, dependency and resource-lock safety, structured acceptance evidence, or VERIFIED/BLOCKED closure across one or more projects.
---

# PM 调度式开发

## Core Principle

把任务文档作为事实源，把 Worker 当作可恢复的执行器，把 Gate 结论建立在机器可校验的证据上。不要用口头“完成”替代结构化 Evidence。

## Read By Need

- 创建、更新或验收任务时，读取 `references/core-contract.md`。
- 使用 Codex 可见 Worker 时，读取 `references/adapters/codex.md` 和 `references/adapters/codex.adapter.json`。
- 使用其它 Agent、CI 或人工执行时，读取 `references/adapters/generic.md`。
- 需要目录、看板、Prompt 和 Heartbeat 示例时，读取 `references/operating-model.md`。
- 分发前运行 `scripts/resolve_pm_dispatch.py`；Gate 判定前运行 `scripts/validate_pm_dispatch.py`。
- 修改本 skill 后运行 `python3 -m unittest discover -s tests -v`。

Schema 和 Adapter JSON 是机器事实源；Markdown 只解释意图，不重新定义字段。
Task/Evidence 当前使用 `schema_version: "2"`；旧文件先运行 `scripts/migrate_pm_dispatch.py`。

## Naming

统一使用机器 ID 和可见名称：

```text
task_id:      BUG-041
display_name: BUG-041 P1 AA 最近诊断记录
worker_name:  BUG-041-impl-w01
worker_label: BUG-041 P1 AA 最近诊断记录 [impl w01]
run_id:       run-BUG-041-impl-w01
attempt_id:   attempt-BUG-041-impl-w01-a01
```

支持 `BUG`、`SPEC`、`ONBOARD`、`RELEASE`、`ENV`、`CHORE`。目录名、`task.yaml.id` 和 `evidence.yaml.task_id` 必须一致。

## Task Panel

用户要求“任务面板”“当前任务”或进度总览时，默认输出紧凑 Markdown 表格：

| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |
| --- | --- | --- | --- | --- |
| 进行中 | BUG-041 最近诊断记录 | P1 | 已完成数据回填，自动测试通过 | 补 API/性能证据，再执行 L3/L4 |

- `任务` 只显示 `<id> <title>`；优先级已有独立列，不重复 Area 或完整 `display_name`。
- `状态` 使用面向 PM 的短标签，如 `进行中`、`待确认`、`待实施`、`环境阻塞`、`可选优化`、`方案待定`、`可选补验`。
- `当前进展` 只写已发生且有事实依据的结果；`下一步` 只写一个可执行动作或明确决策。
- 排序顺序为进行中、阻塞、待确认/待实施、可选项；同组内按 `P0` 到 `P3`。
- 主面板不展示 Owner、Worker、Run、Lease、模型或 Adapter；仅在用户要求详情或存在异常时另加“运行详情”。
- 默认不在表格前后复述字段含义，不使用卡片或逐任务长段落。

## Choose Strategy

- `direct`：当前线程完成小型、低风险、可直接验证的任务；不创建 Run、Attempt、Lease、Heartbeat 或资源锁。
- `single-worker`：一个 Worker 完成实现和验证。
- `batch-worker`：2-4 个同工程、同 Gate、同回归面的任务共享 Worker，但保留独立 Task、Evidence 和结论。
- `full-dispatch`：跨工程、数据库、发布、迁移、安全或真实链路任务按 Gate 串行推进。

默认选择最轻且可验证的策略。缺少真实证据、跨 Owner、跨仓库或出现资源冲突时升级策略。

## Workflow

1. **Read context**
   - 读取看板、Task、Evidence、Decision、活跃 Run、Lease、依赖和资源锁。
   - 编辑前检查 Git 状态，不覆盖用户未提交改动。

2. **Triage**
   - 确定任务类型、优先级、Area、运行模式、策略、通用模型请求、能力和验收表面。
   - 根据命名合同生成 ID、`display_name`、Worker 名和标签。

3. **Define**
   - 按 Schema 创建或更新 `task.yaml` 与 `evidence.yaml`。
   - 写清用户原始路径、存量数据、运行形态、测试数据、L0-L4 和停止条件。

4. **Check safety**
   - 在批量或并行分发前运行 `--tasks-dir` 校验。
   - 依赖未满足、存在依赖环、资源锁冲突、活跃 Run 超限或 Lease 无效时停止分发。

5. **Dispatch**
   - 先用 Resolver 将 `model_request` 和能力要求解析为 `resolution`，不得由 AI 猜 Provider 参数。
   - 按 Resolution 对应的 Provider Adapter 创建真实 Worker，并把真实 Worker ID 与实际模型参数写回 Run。
   - 默认使用用户可见 Worker；只有用户明确允许时才使用内部 sub-agent。
   - 创建 Attempt、Lease、必要资源锁和经授权的 Heartbeat。不得先写“running”再伪造 Worker ID。

6. **Collect evidence**
   - Worker 完成后回收 commit、文件、命令、API、SQL、Browser、截图、日志、ID、升级和发布证据。
   - Evidence Artifact 必须包含来源、主体、结果、时间和稳定引用；L0-L4 引用必须解析到 Artifact ID。

7. **Close**
   - 先运行 validator，再更新 Gate。
   - `CLOSED` 必须具有 verified-like Evidence、`lifecycle.phase=archive`、`closure.status=closed` 和完整接受时间。
   - 失败项转成补证据、返修 Prompt、Blocker 或 PM Decision，不用绿色状态掩盖风险。

## Gate Outcomes

- `VERIFIED`：真实验收证据通过且无 open blocker。
- `L*_VERIFIED_MOCK`：PM 明确接受 Mock fallback，Evidence 标注 `mock_based` 和 `accepted_fallback`。
- `PARTIAL_VERIFIED`：部分证据通过但仍有明确缺口。
- `ENV_BLOCKED`、`CONTRACT_BLOCKED`、`THREAD_BLOCKED`、`PM_BLOCKED`：对应阻塞必须同时存在于 Task 和 Evidence。

UI/L3 必须有结构化 Browser Artifact；API/L2 必须有 API、SQL 或成功 Command Artifact；SQL、Migration 和 Release 必须有 Upgrade 或 Release Artifact。

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 scripts/resolve_pm_dispatch.py docs/tasks/BUG-041/task.yaml --write
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml
python3 scripts/validate_pm_dispatch.py --tasks-dir docs/tasks
python3 scripts/migrate_pm_dispatch.py docs/tasks --write
```

Validator 失败时不要手工覆盖结论。修复 Task/Evidence，或记录真实 Blocker。

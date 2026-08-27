# PM Dispatch Development

面向软件交付的 PM 调度 Skill：用结构化 Task、Evidence、Run/Attempt/Lease、依赖图和资源锁管理单工程、多工程联调和新工程接入。

## 核心变化

- 任务机器 ID 使用 `BUG-041`、`SPEC-042`。
- 人类可见名称使用 `BUG-041 P1 AA 最近诊断记录`。
- Worker 使用唯一机器名和可见标签，例如 `BUG-041-impl-w01` 与 `BUG-041 P1 AA 最近诊断记录 [impl w01]`。
- `CLOSED`、`PARTIAL_VERIFIED`、Blocked 和 verified-like 状态必须有 Evidence。
- Browser/API/SQL 等证据使用结构化 Artifact，不接受任意字符串占位。
- 分发任务线程每 10 分钟只增量检查 Worker 状态、Lease 和最新里程碑；触发里程碑或终态才读取相关完整事实，不创建第二个监控任务。
- 监控或网络中断将存活状态标为 unknown 并保留 Attempt、Lease 所有权和锁；恢复后先 reconcile 原 Worker。
- 普通可恢复问题留在同一 Worker/Attempt；只有安全边界或冻结设计变化才新建 Attempt。
- Validator 检查状态矩阵、硬 Blocker、并发上限、Run/Attempt/Lease、依赖环和资源锁。
- 精简质量检查契约让 Gate Policy 自动校验测试、静态分析、安全检查和 Review Evidence，不增加 Lifecycle 状态。
- 核心协议平台无关；Resolver 根据能力和通用思考强度选择 Adapter，Codex 子 Worker 跟随发布端的默认模型配置。
- Adapter protocol v2 将续接、等待、恢复、终态收集、幂等和状态映射变成机器契约。
- Task v4 保存稳定契约，Runtime v1 保存运行态和事件游标，Evidence 使用 Schema v2；嵌入式 Task v3 可迁移。

## 安装

把目录放到：

```text
~/.codex/skills/pm-dispatch-development
```

在 Codex 中调用：

```text
使用 $pm-dispatch-development 处理这个需求，建立 Task、分发 Worker、回收 Evidence 并完成 Gate 收口。
```

## 任务命名

```text
task_id:      BUG-041
display_name: BUG-041 P1 AA 最近诊断记录
worker_name:  BUG-041-impl-w01
worker_label: BUG-041 P1 AA 最近诊断记录 [impl w01]
run_id:       run-BUG-041-impl-w01
attempt_id:   attempt-BUG-041-impl-w01-a01
```

支持 `BUG`、`SPEC`、`ONBOARD`、`RELEASE`、`ENV`、`CHORE`。

## 分发策略

| 策略 | 用途 |
| --- | --- |
| `direct` | 当前线程处理低风险小任务，不创建 Worker 运行态 |
| `single-worker` | 一个任务级粘性 Worker 跨 Run/Gate 完成实现和验证 |
| `batch-worker` | 2-4 个相似任务共享 Worker，结论保持独立 |
| `full-dispatch` | 跨工程、数据库、发布、迁移和高风险真实链路 |

## 思考强度适配

核心层只使用四档 `reasoning_profile`，不允许 Task 直接指定模型。Codex Adapter 不传 `model`，子 Worker 跟随发布端的默认模型配置；档位只映射 Codex 思考强度。发布任务的临时模型覆盖不会被自动复制。

| 通用档位 | 模型来源 | Codex 思考强度 |
| --- | --- | --- |
| `fast` | 发布端默认 | 继承 |
| `standard` | 发布端默认 | 继承 |
| `deep` | 发布端默认 | `high` |
| `critical` | 发布端默认 | `high` |

具体策略由 [codex.adapter.json](references/adapters/codex.adapter.json) 定义；其它平台仍可按自身能力声明模型路由。

```bash
python3 scripts/resolve_pm_dispatch.py docs/tasks/BUG-041/task.yaml --write
```

## 自动 Gate

Validator 会检查：

- Task ID、类型、优先级、Area、标题与 `display_name` 一致。
- Lifecycle、Verification、Blocker、Closure 状态矩阵一致。
- 终态 Evidence 存在且 conclusion 匹配。
- Artifact 结构、时间、结果和 L0-L4 引用有效。
- 活跃 Run 有真实 Worker ID、唯一 Attempt 和有效 Lease。
- 10 分钟同线程增量 Heartbeat、触发式全文收口、断网所有权保护、Worker 复用和并发上限有效。
- Board 依赖存在且无环。
- Active resource lock 绑定 Active Run，且不超过 Run Lease。

```bash
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml --automation-dir ~/.codex/automations
python3 scripts/validate_pm_dispatch.py --tasks-dir docs/tasks
```

## 自检

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_skill_consistency.py
python3 -m py_compile scripts/*.py tests/*.py
for file in references/schemas/*.json references/adapters/*.adapter.json; do python3 -m json.tool "$file" >/dev/null; done
```

旧 Task/Evidence 先 dry-run 检查，再显式写回：

```bash
python3 scripts/migrate_pm_dispatch.py docs/tasks
python3 scripts/migrate_pm_dispatch.py docs/tasks --write
```

写回前会验证 Task v4、Runtime v1 或 Evidence v2 输出；原 Task/Evidence 按源版本备份，Runtime 与空事件日志作为 sidecar 创建。默认面板只显示可行动项；其它视图按需读取：

```bash
python3 scripts/render_task_panel.py --tasks-dir docs/tasks
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --view waiting-user
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --task SPEC-042
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --view all
```

分发前生成并校验精益 Context Packet；确定性基线只记录字符、字节和行数，不伪造模型 Token：

```bash
python3 scripts/measure_context_baseline.py --tasks-dir docs/tasks \
  --board docs/dispatch-board.md --output /tmp/pm-context-baseline.json
python3 scripts/build_context_packet.py docs/tasks/SPEC-042/task.yaml \
  --gate implementation --verification-command "python3 -m unittest"
python3 scripts/validate_context_packet.py \
  docs/tasks/SPEC-042/context/active-context.json \
  --prompt docs/tasks/SPEC-042/prompts/01-implementation.md
```

Phase 3-6 的一次性预检会生成 Evidence Digest、工程快照、恢复账本和 Context Packet，默认写到项目外临时目录，减少重复扫描和 Git 污染：

```bash
python3 scripts/dispatch_preflight.py docs/tasks/SPEC-042/task.yaml \
  --project-root . --gate implementation \
  --focus frontend/app/page.tsx \
  --verification-command "python3 -m unittest"
```

## 文件职责

- `SKILL.md`：触发后的操作顺序和按需读取路由。
- `references/core-contract.md`：平台无关的不变量。
- `references/task-examples.md`：Task、Worker Runtime 和 Evidence 结构示例。
- `references/prompts.md`：Worker 与 Heartbeat Prompt。
- `references/autonomy.md`：不确定性、恢复预算与硬 Blocker 判定。
- `references/task-panel.md`：任务面板展示合同。
- `references/closure.md`：终态 Gate 和用户收口报告。
- `references/adapters/*.adapter.json`：机器可读 Provider 策略。
- `references/adapters/*.md`：Provider 操作说明。
- `references/schemas/`：正式数据结构。
- `scripts/validate_pm_dispatch.py`：Gate、依赖图和资源锁校验。
- `scripts/validate_skill_consistency.py`：检查监控周期、协议版本和 Runtime 契约跨文件一致。
- `scripts/resolve_pm_dispatch.py`：能力、思考强度和 Provider 回退策略解析。
- `scripts/adapter_protocol.py`：构建 Worker 操作 envelope 并解析 Provider 结果。
- `scripts/reconcile_worker_liveness.py`：确定性处理续租、断线宽限、Attempt 过期和锁释放。
- `scripts/record_runtime_event.py`：校验并追加不可变 Runtime Event，拒绝重复 ID 和时间倒序。
- `scripts/migrate_pm_dispatch.py`：嵌入式 Task 到 Task v4/Runtime v1、旧 Evidence 到 v2 的保守迁移。
- `scripts/render_task_panel.py`：有视图、限额和 RELEASE 折叠的五列任务面板。
- `scripts/measure_context_baseline.py`：确定性测量看板、Task、Evidence、Prompt 和面板上下文表面。
- `scripts/build_context_packet.py`：从事实源生成带来源 SHA 的精益 Context Packet。
- `scripts/validate_context_packet.py`：校验 Packet、来源漂移、字符预算和 Prompt 全文读取权限。
- `scripts/build_evidence_digest.py` / `scripts/validate_evidence_digest.py`：从 Evidence v2 派生并校验当前状态摘要。
- `scripts/build_project_snapshot.py`：生成 Git、文件结构和焦点文件的确定性工程快照。
- `scripts/manage_recovery_ledger.py`：按 Gate/失败指纹计数恢复路径并执行三路径熔断。
- `scripts/dispatch_preflight.py`：串联摘要、快照、恢复账本和 Context Packet 的单入口预检。
- `tests/`：契约、Resolver、迁移和 Gate 持久回归测试。

机器事实源是 Schema、Adapter JSON 和 validator。README 不重新定义字段。

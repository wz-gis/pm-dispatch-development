# PM Dispatch Development

面向软件交付的 PM 调度 Skill：用结构化 Task、Evidence、Run/Attempt/Lease、依赖图和资源锁管理单工程、多工程联调和新工程接入。

## 核心变化

- 任务机器 ID 使用 `BUG-041`、`SPEC-042`。
- 人类可见名称使用 `BUG-041 P1 AA 最近诊断记录`。
- Worker 使用唯一机器名和可见标签，例如 `BUG-041-impl-w01` 与 `BUG-041 P1 AA 最近诊断记录 [impl w01]`。
- `CLOSED`、`PARTIAL_VERIFIED`、Blocked 和 verified-like 状态必须有 Evidence。
- Browser/API/SQL 等证据使用结构化 Artifact，不接受任意字符串占位。
- Validator 检查状态矩阵、并发上限、Heartbeat、Run/Attempt/Lease、依赖环和资源锁。
- 核心协议平台无关；Resolver 根据能力和通用模型请求选择 Adapter，实际参数写入 Resolution。
- Adapter protocol v1 将 Worker transport、输入、超时和输出路径变成机器契约。
- Task/Evidence 使用 Schema v2，旧文档可通过迁移脚本升级。

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
| `single-worker` | 一个 Worker 完成实现和验证 |
| `batch-worker` | 2-4 个相似任务共享 Worker，结论保持独立 |
| `full-dispatch` | 跨工程、数据库、发布、迁移和高风险真实链路 |

## 模型适配

核心层只使用四档 `reasoning_profile`。Codex Adapter 当前使用 `gpt-5.6-sol`，映射如下：

| 通用档位 | Codex 参数 |
| --- | --- |
| `fast` | `low` |
| `standard` | `medium` |
| `deep` | `high` |
| `critical` | `xhigh` |

具体策略由 [codex.adapter.json](references/adapters/codex.adapter.json) 定义。[external-cli.adapter.json](references/adapters/external-cli.adapter.json) 证明其它平台可以使用不同 Worker 命令、监控模式和推理参数，不需要修改核心 Schema。

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
- Heartbeat 元数据和并发上限有效。
- Board 依赖存在且无环。
- Active resource lock 绑定 Active Run，且不超过 Run Lease。

```bash
python3 scripts/validate_pm_dispatch.py docs/tasks/BUG-041/task.yaml
python3 scripts/validate_pm_dispatch.py --tasks-dir docs/tasks
```

## 自检

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py tests/*.py
for file in references/schemas/*.json references/adapters/*.adapter.json; do python3 -m json.tool "$file" >/dev/null; done
```

旧 Task/Evidence 先 dry-run 检查，再显式写回：

```bash
python3 scripts/migrate_pm_dispatch.py docs/tasks
python3 scripts/migrate_pm_dispatch.py docs/tasks --write
```

写回前会验证完整 v2 输出，原文件保存为 `.v1.bak`，再通过原子替换更新。任务面板使用确定性状态映射和快照测试：

```bash
python3 scripts/render_task_panel.py --tasks-dir docs/tasks
```

## 文件职责

- `SKILL.md`：触发后的操作顺序和按需读取路由。
- `references/core-contract.md`：平台无关的不变量。
- `references/adapters/*.adapter.json`：机器可读 Provider 策略。
- `references/adapters/*.md`：Provider 操作说明。
- `references/operating-model.md`：目录、Task、Evidence 和 Prompt 示例。
- `references/schemas/`：正式数据结构。
- `scripts/validate_pm_dispatch.py`：Gate、依赖图和资源锁校验。
- `scripts/resolve_pm_dispatch.py`：能力、模型和回退策略解析。
- `scripts/adapter_protocol.py`：构建 Worker 操作 envelope 并解析 Provider 结果。
- `scripts/migrate_pm_dispatch.py`：旧格式到 Schema v2 的保守迁移。
- `scripts/render_task_panel.py`：固定五列任务面板渲染。
- `tests/`：契约、Resolver、迁移和 Gate 持久回归测试。

机器事实源是 Schema、Adapter JSON 和 validator。README 不重新定义字段。

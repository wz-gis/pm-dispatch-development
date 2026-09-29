# PM Dispatch Development

[English](README.md) | 简体中文 | [统计口径与复算](references/usage-evidence.md)

面向持续软件交付的 PM Skill：把 Bug 修复和功能需求组织成可恢复的任务，用精简看板、可复用 Worker 和结构化证据完成验收。适合跨会话、跨仓库的持续工作；低风险小改动仍可留在当前对话直接处理。

这是 Skill 加本地 Python 工具，不是托管平台，也不是拦截所有调用的 MCP 运行时。

## 有数据的优势

2026-09-04 对一个实际工程进行匿名只读统计：

| 观测项 | 数字 | 正确理解 |
| --- | ---: | --- |
| 去重后的任务记录 | **48 个** | 37 个 Bug、10 个 Spec、1 个 Release；排除 2 个模板/旧别名文档 |
| 默认可行动面板 | **1,928 字符** | 全量面板为 9,472 字符，阅读文本量减少 **79.65%** |
| 历史看板对比 | **27,038 → 1,928 字符** | 当前决策所需文本量减少 **92.87%**，不是等量内容的无损压缩 |
| 已存 Prompt 文档 | **190 份** | 是历史文件数，不是模型调用次数 |

这些是单工程、混合版本样本的 Unicode 字符实测，不代表同等比例的 Token、费用、耗时或成功率改善。默认视图有意不展示已关闭/不相关细节，完整信息仍在事实源。公式、样本边界和公开报告见[统计说明](references/usage-evidence.md)。

## 高频使用场景

以下排序参考实际反复出现的使用诉求；只有上表的任务类型分布是量化频率。

| 场景 | 调用 Skill 后可以这样说 | 交付结果 |
| --- | --- | --- |
| 每日任务梳理 | 给我可行动任务面板，每项只写一个下一步 | 五列看板，默认最多 8 行 |
| Bug 修复 | 分发 BUG-001，在本对话监控 | 可见 Worker、冻结范围、聚焦验证与证据报告 |
| 功能开发和验收 | 分发 SPEC-002，完成实现和浏览器验收 | 同一 Worker 跨 Gate 复用，只追加差量 |
| Worker 断线 | 先核对原 Worker 和 Lease，不要直接替换 | 保留所有权，从里程碑和 Artifact 恢复 |
| 环境导致无法验收 | 区分已完成代码和缺失的真实 API/页面证据 | 明确 partial/blocked 状态和一个解阻动作 |

跨仓库联调、数据库迁移和发布也使用同一套记录，但需要更广的验证与依赖/资源锁检查。Git 提交、推送、生产变更及创建可见任务，仍受用户要求的范围和宿主授权约束。

## 开始使用

本仓库沿用的 Codex 安装路径：

```text
~/.codex/skills/pm-dispatch-development
```

```text
使用 $pm-dispatch-development 处理这个 Bug，
选择最轻的可验证策略，报告真实进展和下一步。
```

本地脚本要求 Python 3.11+；锁相关脚本使用 POSIX `fcntl`，适用于 macOS/Linux，未验证原生 Windows。JSON 和受支持的 YAML 子集无需第三方依赖，完整 YAML 语法可能需要 PyYAML。

Codex 按[当前工具能力](references/adapters/codex-routing.md)选择执行方式：内置子代理通过父线程完成通知收口；独立可见 Worker 需要任务和 Heartbeat 工具。内部子代理不等于可见后台线程，也不承诺断线后持续监控。两条路径都不可用时，在范围允许的情况下使用 `direct`。外部代理仍默认不启用，只有当前请求明确选择且宿主策略允许时才能使用；本 Skill 不附带外部模型、账号或凭据。

## 工作方式

```text
每个项目一个 PM 对话
  -> 内置子代理 + 父线程完成通知
  或 独立可见 Worker + 同一 PM 内的任务 Heartbeat
  -> 相关工作与 Gate 复用选定的 Worker
  <- 证据、最新里程碑、一个下一步
```

同一项目的 Bug 和 Spec 共用 PM 对话。精简上下文后仍无法可靠继续时，先准备必要交接包，获得用户同意后才创建替代 PM。迁移沿用原 Worker；Run 次数本身不触发替换。详见[协调器迁移规则](references/project-coordinator.md)。

PM 指当前对话中负责项目协调的 Agent，Worker 是执行指定范围的 Agent/任务。Task 保存稳定范围和验收契约，Runtime 保存运行态与所有权，Evidence 保存结果证据。Run 是一次执行单元，Attempt 是它的可恢复尝试，Lease 是有期限的所有权，Gate 是证据校验关口。编译通过不等于真实链路验收通过。

任务显示名示例：`BUG-001 P1 API 修复分页`，依次为 ID、优先级、模块和标题。公开示例均为虚构。L0-L4 是本 Skill 的证据等级，不是行业认证；具体要求见[收口契约](references/closure.md)。

## 调度成本边界

| 控制项 | 默认值 | 不能据此承诺什么 |
| --- | --- | --- |
| 计划巡检 | 每 10 分钟，最多 6 次/小时 | 相比 5 分钟少 50% 计划检查机会；不含用户主动查询 |
| 正超时等待 | 每 Run 最多 1 次、最长 30 秒 | 限制请求的阻塞等待，不等于总耗时或 Token |
| Worker Prompt | 首轮 6,000、续跑 3,000 字符 | 续跑上限低 50%，不是缓存命中率或实测节省 |
| 批量分发 | 2-4 个适合的任务共享 Worker | 相比逐任务创建少 50%-75% Worker，不保证任务耗时降低 |
| 恢复预算 | 同方法重试 1 次，另试最多 2 条路径 | 有界恢复，不保证成功 |

监控在分发任务的当前对话内，不另建监控任务。规划脚本本身不调用模型，但宿主 Heartbeat 唤醒仍可能消耗模型 Token。Skill 不能隐藏原生 MCP 工具，也不能让断网/休眠的宿主持续运行；授权和可选会话审计用于发现违规，恢复前保留任务所有权。

## 策略与适配

- `direct`：本对话完成低风险小改动。
- `single-worker`：同一个 Worker 完成实现、联调、修复和验收。
- `batch-worker`：同工程/同 Gate 的 2-4 个相关任务共用 Worker，结论独立。
- `full-dispatch`：高风险、跨工程工作按依赖顺序交付。

Codex Worker 使用发布端默认模型，不自动复制父任务临时模型覆盖。`fast`/`standard` 继承思考强度，`deep`/`critical` 映射为 `high`。其他宿主需要实现对应 Adapter；附带 external CLI 定义是适配示例，不是所有 Agent 开箱即用的集成。

## 查看与自检

在 Skill 目录执行，替换工程路径占位符：

```bash
PROJECT=/path/to/project
python3 scripts/render_task_panel.py --tasks-dir "$PROJECT/docs/tasks"
python3 scripts/validate_pm_dispatch.py --tasks-dir "$PROJECT/docs/tasks"
python3 scripts/measure_context_baseline.py --tasks-dir "$PROJECT/docs/tasks" \
  --board "$PROJECT/docs/dispatch-board.md" --public \
  --output /tmp/pm-public-baseline.json
python3 -m unittest discover -s tests
python3 scripts/validate_skill_consistency.py
```

内置面板仍默认中文展示；Agent 按用户语言解释，英文列含义见[面板文档](references/task-panel.md)。Schema 字段、状态值和机器 ID 不随语言改变。核心记录版本为 Task v4 / Runtime v1 / Evidence v2，旧记录先只读检查再迁移。

## 隐私边界

仅 `measure_context_baseline.py --public` 使用固定标签与数字白名单导出。普通面板、Task/Evidence、Prompt、会话和快照都可能含隐私，不会自动脱敏。不要发布原始材料或本地备份；忽略规则不会删除已跟踪文件和 Git 历史。

本次公开统计不包含真实项目名、主目录路径、任务标题、Worker ID、凭据或会话正文。汇总移除了直接标识符，但不构成形式化匿名保证。

## 文档入口

[执行规则](SKILL.md) · [核心契约](references/core-contract.md) · [数据示例](references/task-examples.md) · [Prompt](references/prompts.md) · [Codex Adapter](references/adapters/codex.md) · [上下文预算](references/context-budget.md)

执行参考文档统一使用英文，避免双份规则漂移；本指南保留完整中文使用说明。机器事实源仍是 Schema、Adapter JSON、Resolver 和 Validator。

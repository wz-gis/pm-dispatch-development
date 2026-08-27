# Closure And Terminal Report

在任何 Worker、Run、Attempt 或 direct 任务进入终态后，先用 Task/Evidence 和 Validator 确认真实状态，再主动向用户报告。Heartbeat 触发的终态回收也遵守同一合同；停止 Automation 后不得只报告“已停止 heartbeat”。

## Gate Outcomes

- `VERIFIED`：真实验收证据通过且无 open blocker。
- `L*_VERIFIED_MOCK`：PM 明确接受 Mock fallback，Evidence 标注 `mock_based` 和 `accepted_fallback`。
- `PARTIAL_VERIFIED`：部分证据通过但仍有明确缺口。
- `ENV_BLOCKED`、`CONTRACT_BLOCKED`、`THREAD_BLOCKED`、`PM_BLOCKED`：对应 Blocker 同时存在于 Task 和 Evidence。
- `CLOSED`：具有 verified-like Evidence、`lifecycle.phase=archive`、`closure.status=closed` 和完整接受时间。

UI/L3 需要结构化 Browser Artifact；API/L2 需要 API、SQL 或成功 Command Artifact；SQL、Migration 和 Release 需要 Upgrade 或 Release Artifact。Closure 还要求 Gate Policy 计算出的 required/conditional 质量检查全部通过；skipped 必须未触发且有原因。

## Report Fields

- 任务状态与真实验收级别，不能把 L2/L3 写成 L4。
- 本轮实际完成的提交、同步、部署、测试和结构化证据。
- 未关闭 Blocker、缺失证据、环境限制、风险和用户授权。
- 用户需要执行的登录、验证码、支付授权、域名或生产操作；不得索取或记录 Secret。
- 产品与 PM commit，以及一个最优先的下一步；无后续动作时明确说明。

```text
<TASK_ID> 已收口为 <状态>，不是/已是 <VERIFIED/Lx>。
已通过：<关键 Gate 和证据>。
未通过/未关闭：<缺口和 blocker>。
需要你操作：<如无则写“暂无”>。
提交：产品 <commit 或无>；PM <commit 或无>。
下一步：<一个动作>。
```

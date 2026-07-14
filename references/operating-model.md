# PM Dispatch Operating Model

## Contents

- Repository layout
- Direct task example
- Codex Worker example
- Evidence example
- Worker Prompt
- Heartbeat Prompt
- Board operations

Field definitions live in the JSON Schemas. This document provides operational examples only.

## Repository Layout

```text
docs/
├── dispatch-board.md
├── dispatcher-runbook.md
└── tasks/
    └── BUG-041/
        ├── task.yaml
        ├── evidence.yaml
        ├── evidence.md
        ├── decisions.md
        └── prompts/
```

Use `BUG-041 P1 AA 最近诊断记录` on the board. Use `BUG-041` for directories and references.

## Direct Task Example

```yaml
schema_version: "2"
id: BUG-041
display_name: BUG-041 P1 AA 最近诊断记录
title: 最近诊断记录
type: bug
priority: P1
status: TRIAGED
mode: single-project
area: [AA]
lifecycle:
  phase: triage
  owner: pm
  accepted_scope: null
  next_action: define acceptance
  updated_at: 2026-07-13T12:00:00Z
verification:
  required_levels: [L1]
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
  graph_checked_at: 2026-07-13T12:00:00Z
resources:
  locks: []
dispatch:
  strategy: direct
  provider_policy:
    mode: local
    provider: local
  required_capabilities: []
  required_evidence_kinds: []
  reason: Small task handled in the current thread.
  worker_required: false
  heartbeat_required: false
  selected_at: 2026-07-13T12:00:00Z
  max_parallel_workers: null
  model_request: null
  fallback_policy: null
  resolution: null
  batch: null
  heartbeat: null
  escalation_triggers: []
runs: []
last_updated: 2026-07-13T12:00:00Z
```

## Codex Worker Example

For a visible Codex Worker, use the Codex Adapter values and record actual thread creation results.

```yaml
dispatch:
  strategy: single-worker
  provider_policy:
    mode: pinned
    provider: codex
  required_capabilities: [background-worker, code-edit, git, heartbeat, shell]
  required_evidence_kinds: [command, browser, log]
  reason: Implementation and L3 verification need an isolated Worker.
  worker_required: true
  heartbeat_required: true
  selected_at: 2026-07-13T12:00:00Z
  max_parallel_workers: 1
  model_request:
    quality: frontier
    reasoning_profile: standard
    latency: normal
    cost: balanced
  fallback_policy:
    mode: strict
    allowed_providers: [codex]
    allow_model_substitution: false
    allow_manual_monitoring: false
  resolution:
    provider: codex
    adapter_version: "1"
    model_id: gpt-5.6-sol
    reasoning_profile: standard
    provider_reasoning_effort: medium
    worker_type: codex-thread
    monitor_mode: heartbeat
    capabilities: [background-worker, code-edit, git, heartbeat, shell]
    evidence_kinds: [browser, command, log]
    resolved_at: 2026-07-13T12:00:00Z
    reason: Pinned Codex Adapter satisfies all requested capabilities.
  batch: null
  heartbeat:
    automation_id: automation-001
    interval_minutes: 15
    max_checks: 6
    stop_condition: run terminal
    lightweight: true
    status: active
  escalation_triggers: []
runs:
  - run_id: run-SPEC-042-impl-w01
    gate: implementation
    worker_type: codex-thread
    worker_name: SPEC-042-impl-w01
    worker_label: SPEC-042 P1 WEB 新增页面 [impl w01]
    worker_id: codex-thread:thread-id
    provider: codex
    adapter_version: "1"
    model_id: gpt-5.6-sol
    reasoning_profile: standard
    provider_reasoning_effort: medium
    resolution_reason: Pinned Codex Adapter satisfies all requested capabilities.
    status: running
    allow_parallel: false
    started_at: 2026-07-13T12:00:00Z
    finished_at: null
    attempts:
      - attempt_id: attempt-SPEC-042-impl-w01-a01
        status: running
        started_at: 2026-07-13T12:00:00Z
        finished_at: null
        lease:
          holder: run-SPEC-042-impl-w01
          acquired_at: 2026-07-13T12:00:00Z
          heartbeat_at: 2026-07-13T12:00:00Z
          expires_at: 2026-07-13T13:00:00Z
          renew_count: 0
```

## Evidence Example

```yaml
schema_version: "2"
task_id: SPEC-042
generated_at: 2026-07-13T12:30:00Z
verification:
  changed_surface: [ui page]
  original_user_path: Existing user opens the page and saves.
  runtime_shape: dev
  test_data: [existing-user]
  levels:
    L3:
      status: pass
      summary: Existing-user workflow passed.
      evidence_refs: [browser-001]
      commands: []
  existing_data_regression: passed
  uncovered_items: []
artifacts:
  commands: []
  commits: [abc123]
  files_changed: [src/page.tsx]
  api: []
  sql: []
  browser:
    - artifact_id: browser-001
      kind: browser
      source: codex-browser
      subject: Existing user opens and saves the page.
      result: pass
      captured_at: 2026-07-13T12:30:00Z
      evidence_ref: evidence/browser-001.json
      status_code: null
      digest: null
  screenshots: []
  logs: []
  ids: []
  upgrade_path: []
  release_path: []
runs: []
blockers: []
conclusion:
  status: VERIFIED
  evidence_level: L3
  mock_based: false
  real_chain_verified: true
  accepted_fallback: null
  notes: null
```

## Worker Prompt

```markdown
任务：SPEC-042 P1 WEB 新增页面
身份：SPEC-042-impl-w01 / run-SPEC-042-impl-w01 / attempt-SPEC-042-impl-w01-a01
Resolution：provider=codex，model=gpt-5.6-sol，reasoning_profile=standard，provider_effort=medium
允许范围：<repo/files>
禁止范围：<repos/files>
目标：<observable outcome>
用户原始路径：<existing-user path>
必需证据：commit、files、commands、API/SQL/Browser Artifacts、existing-data regression
资源锁：<locks>
停止条件：<blocked conditions>
```

## Heartbeat Prompt

```markdown
轻量巡检 run-SPEC-042-impl-w01。
运行中只读取 Worker 状态和 Lease；不要重读完整文档或制造提交。
完成、失败、失联或 Lease 临期时，再读取 Task/Evidence，回收结构化证据并运行 validator。
终态后停止 automation。
```

## Board Operations

- Generate the canonical panel with `python3 scripts/render_task_panel.py --tasks-dir docs/tasks`; status mapping and ordering are code-defined and snapshot-tested.
- 默认任务面板使用固定五列，不把运行时元数据挤入主视图：

| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |
| --- | --- | --- | --- | --- |
| 进行中 | BUG-041 最近诊断记录 | P1 | 来源归一化及历史回填中；备份和自动测试已通过 | 补 API/性能证据，再实施页面及 L3/L4 |
| 待确认 | BUG-039 全量扫描错误码无结果 | P0 | 已定位并建档 | 确认进入公共契约 |
| 环境阻塞 | BUG-033 规则保存启用与描述提取 | P0 | 代码已修复，构建通过 | 修复服务类加载环境后补 API/页面验收 |
| 可选补验 | SPEC-001 ZIP 源码包接入 | P1 | Mock L3 已通过 | 补真实内网 ZIP L4 |

- `任务` 使用 `<id> <title>`；完整 `display_name` 留在 Task 文档和 Worker 标签中。
- `当前进展` 概括已验证事实，`下一步` 保持为单个动作或决策。
- 先排进行中和阻塞项，再排待确认/待实施，最后排可选项；同组内按优先级排序。
- Owner、Worker Label、Run、Lease、模型与 Adapter 仅在用户要求或状态异常时放入独立“运行详情”。
- 批处理共享 Worker，不共享 Task 状态或 Evidence 结论。
- 并行前运行 `--tasks-dir`；有环、缺依赖、锁冲突或并发超限时停止。
- 关单前运行单任务 validator；`CLOSED` 后归档并停止 Heartbeat。

# Task And Evidence Examples

这些片段展示结构和运行关系；完整字段与约束以 JSON Schema 为准。

## Contents

- Repository layout
- Direct dispatch
- Codex Worker runtime
- Quality checks
- Evidence Artifact

## Repository Layout

```text
docs/
├── dispatch-board.md
└── tasks/
    └── BUG-041/
        ├── task.yaml
        ├── runtime.yaml
        ├── events.jsonl
        ├── evidence.yaml
        ├── decisions.md
        └── prompts/
```

## Direct Dispatch

```yaml
schema_version: "4"
runtime_file: runtime.yaml
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
quality_checks:
  policy: risk-scaled
  checks:
    - id: unit-test
      requirement: required
      when_changed_surface: []
      evidence_kinds: [command]
blockers: []
closure: {status: open, accepted_by: null, accepted_at: null, closed_at: null, archived_to: null, notes: null}
dependencies: {requires: [], blocks: [], graph_checked_at: 2026-07-13T12:00:00Z}
dispatch:
  strategy: direct
  provider_policy: {mode: local, provider: local}
  required_capabilities: []
  required_evidence_kinds: []
  reason: Small task handled in the current thread.
  worker_required: false
  heartbeat_required: false
  max_parallel_workers: null
  reasoning_profile: null
  fallback_policy: null
  autonomy_policy:
    default_action: proceed
    clarification_policy: material-irreversible-only
    blocker_policy: hard-only
    verification_policy: risk-scaled
    recovery: {same_method_retries: 1, alternate_method_attempts: 2, rediscovery_limit: 1}
  design_freeze: null
  worker_reuse: null
  batch: null
  escalation_triggers: []
last_updated: 2026-07-13T12:00:00Z
```

```yaml
# runtime.yaml
schema_version: "1"
task_id: BUG-041
task_schema_version: "4"
resolution: null
selected_at: 2026-07-13T12:00:00Z
heartbeat: null
resources: {locks: []}
runs: []
event_log_file: events.jsonl
last_updated: 2026-07-13T12:00:00Z
```

## Codex Worker Runtime

```yaml
# task.yaml excerpt
dispatch:
  strategy: single-worker
  provider_policy: {mode: pinned, provider: codex}
  required_capabilities: [background-worker, code-edit, git, heartbeat, shell]
  required_evidence_kinds: [browser, command, log]
  reason: Implementation and L3 verification need an isolated Worker.
  worker_required: true
  heartbeat_required: true
  max_parallel_workers: 1
  reasoning_profile: standard
  fallback_policy:
    mode: strict
    allowed_providers: [codex]
    allow_manual_monitoring: false
  autonomy_policy:
    default_action: proceed
    clarification_policy: material-irreversible-only
    blocker_policy: hard-only
    verification_policy: risk-scaled
    recovery: {same_method_retries: 1, alternate_method_attempts: 2, rediscovery_limit: 1}
  design_freeze:
    status: frozen
    frozen_at: 2026-07-13T12:00:00Z
    scope: [frontend/app]
    constraints: [Keep existing routes compatible.]
    acceptance: [L3 browser flow passes with structured evidence.]
    fingerprint: sha256:121c0df11c3afeca791046183aad696b7e3ca5492b81bfcbcfa5d5a21fc724d4
    change_policy: material-only-new-attempt
  worker_reuse:
    mode: sticky
    reuse_across_gates: true
    max_runs_per_worker: 6
    replacement_triggers: [irrecoverable-worker, safety-boundary-change, design-freeze-change, provider-change, context-saturated, independent-review]
  batch: null
  escalation_triggers: []
```

```yaml
# runtime.yaml
schema_version: "1"
task_id: SPEC-042
task_schema_version: "4"
resolution:
  provider: codex
  adapter_version: "9"
  model_id: null
  reasoning_profile: standard
  provider_reasoning_effort: inherit
  worker_type: codex-thread
  monitor_mode: heartbeat
  capabilities: [background-worker, code-edit, git, heartbeat, shell]
  evidence_kinds: [browser, command, log]
  resolved_at: 2026-07-13T12:00:00Z
  reason: Pinned Codex Adapter satisfies all requested capabilities.
selected_at: 2026-07-13T12:00:00Z
heartbeat:
  automation_id: automation-001
  coordinator_thread_id: codex-thread:pm-id
  target_run_id: run-SPEC-042-impl-w01
  context_policy: coordinator
  scan_scope: incremental
  read_set: [worker-status, lease, latest-milestone]
  full_scan_triggers: [milestone, terminal, safety-boundary-change, design-freeze-change]
  prompt_max_chars: 220
  interval_minutes: 10
  max_checks: 6
  stop_condition: run terminal
  lightweight: true
  status: active
resources: {locks: []}
runs:
  - run_id: run-SPEC-042-impl-w01
    gate: implementation
    worker_type: codex-thread
    worker_name: SPEC-042-impl-w01
    worker_label: SPEC-042 P1 WEB 新增页面 [impl w01]
    worker_id: codex-thread:thread-id
    worker_replacement_reason: null
    provider: codex
    adapter_version: "9"
    model_id: null
    reasoning_profile: standard
    provider_reasoning_effort: inherit
    resolution_reason: Pinned Codex Adapter satisfies all requested capabilities.
    design_fingerprint: sha256:121c0df11c3afeca791046183aad696b7e3ca5492b81bfcbcfa5d5a21fc724d4
    status: running
    allow_parallel: false
    started_at: 2026-07-13T12:00:00Z
    finished_at: null
    continuation_token: null
    event_cursor: null
    last_operation: create
    last_idempotency_key: create-SPEC-042-a01
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
          progress_seq: 0
          last_progress_at: 2026-07-13T12:00:00Z
          last_progress_summary: Worker dispatched; implementation pending.
          event_cursor: null
          liveness_state: live
          monitor_gap_started_at: null
          disconnect_probe_count: 0
          disconnect_first_seen_at: null
event_log_file: events.jsonl
last_updated: 2026-07-13T12:00:00Z
```

`events.jsonl` 每行一个 Runtime Event，例如：

```json
{"schema_version":"1","event_id":"evt-SPEC-042-001","event_type":"worker-created","task_id":"SPEC-042","occurred_at":"2026-07-13T12:00:00Z","run_id":"run-SPEC-042-impl-w01","attempt_id":"attempt-SPEC-042-impl-w01-a01","provider":"codex","worker_id":"codex-thread:thread-id","payload":{"idempotency_key":"create-SPEC-042-a01"}}
```

## Context Packet

Context Packet 由脚本生成，不手写、不作为事实源。典型切片如下：

```json
{
  "schema_version": "1",
  "derived": true,
  "mode": "initial",
  "task": {"id": "SPEC-042", "schema_version": "4", "display_name": "SPEC-042 P1 WEB 新增页面", "title": "新增页面", "priority": "P1", "status": "IN_IMPL", "area": ["WEB"]},
  "execution": {"run_id": "run-SPEC-042-impl-w01", "run_status": "running", "attempt_id": "attempt-SPEC-042-impl-w01-a01", "attempt_status": "running", "gate": "implementation", "design_fingerprint": "sha256:121c0df11c3afeca791046183aad696b7e3ca5492b81bfcbcfa5d5a21fc724d4", "latest_milestone": null},
  "objective": "实现已冻结的新页面用户路径。",
  "scope": {"allowed": ["src/page.tsx"], "prohibited": ["不得修改生产数据"], "constraints": []},
  "confirmed_facts": [],
  "open_failure": null,
  "open_blockers": [],
  "dependencies": [],
  "locks": [],
  "evidence_gaps": ["L3 Browser"],
  "verification_commands": ["project-test-command"],
  "budgets": {"packet_max_chars": 8000, "initial_prompt_max_chars": 6000, "continuation_prompt_max_chars": 3000, "full_read_allowed": false, "full_read_trigger": null, "full_read_triggers": ["design-freeze-change", "safety-boundary-change", "contract-review", "schema-migration", "terminal-closure", "forensic-diagnosis"]},
  "source_digests": {"task": {"path": "../task.yaml", "sha256": "sha256:..."}, "runtime": {"path": "../runtime.yaml", "sha256": "sha256:..."}, "evidence": null},
  "generated_at": "2026-07-13T12:00:00Z",
  "packet_sha256": "sha256:..."
}
```

## Quality Checks

Quality checks do not add Lifecycle phases. Commands come from the project or CI; the core records and validates results.

```yaml
quality_checks:
  policy: risk-scaled
  checks:
    - {id: unit-test, requirement: required, when_changed_surface: [], evidence_kinds: [command]}
    - {id: static-analysis, requirement: required, when_changed_surface: [], evidence_kinds: [command, log]}
    - {id: security, requirement: conditional, when_changed_surface: [auth, dependency, secret, sql, upload], evidence_kinds: [command, log]}
    - {id: review, requirement: required, when_changed_surface: [], evidence_kinds: [log]}
```

## Evidence Artifact

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
quality_checks:
  - id: unit-test
    status: passed
    tool: project-test-runner
    summary: Unit tests passed.
    evidence_refs: [command-001]
    skip_reason: null
    checked_at: 2026-07-13T12:30:00Z
artifacts:
  commands:
    - artifact_id: command-001
      kind: command
      source: ci
      subject: Unit tests
      result: pass
      captured_at: 2026-07-13T12:30:00Z
      evidence_ref: evidence/command-001.txt
      command: project-test-command
      exit_code: 0
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

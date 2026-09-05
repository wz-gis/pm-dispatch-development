# Usage Evidence And Publication Scope

[English guide](../README.md) | [中文指南](../README.zh-CN.md) | [Anonymous snapshot](usage-baseline.json)

## Sample

Measured locally on **2026-09-04** from one ongoing software project. Of 50 discovered Task documents, 48 canonical task-directory records were included; one template and one legacy alias were excluded. Legacy `taskId` is normalized in memory. Duplicate YAML/JSON records for one ID count once. No project files were migrated.

| Stored task type | Count | Share of 48 |
| --- | ---: | ---: |
| Bug | 37 | 77.08% |
| Feature/specification | 10 | 20.83% |
| Release | 1 | 2.08% |

Rounding may not total 100%. This is an inventory of stored records, not a completion rate, weekly workload, or a count of Skill invocations. Records mix legacy/current schemas; measurements do not certify their historical acceptance claims.

The scanner also found 190 prompt files and 20 Evidence files through the declared/default evidence path. It measured 938,696 characters across selected Task, discovered Evidence, Prompt, and board files. This is stored history, **not context actually loaded on every run**, nor an exhaustive audit of all possible legacy artifact links.

Repeated user requests informed the documented scenarios: task triage, isolated bug repair, feature acceptance, same-Worker continuation, outage recovery, and optional external implementation. Only task-type counts above are quantified; request-frequency rankings were not measured.

## Reading Surface

| Surface | Unicode characters |
| --- | ---: |
| Historical dispatch board | 27,038 |
| All-task panel | 9,472 |
| Default actionable panel | 1,928 |

- Against the all-task panel: `(1 - 1928 / 9472) * 100 = 79.65%`.
- Against the historical board: `(1 - 1928 / 27038) * 100 = 92.87%`.

Both panels use the same selected inventory and the existing renderer. The default view filters and caps rows; it is not a lossless replacement for the full board. Chinese source/display text remains in the private measurement, but no titles or panel bodies are exported.

Do not label these percentages as token/cost savings, latency improvements, or model-cache hit rates. No tokenizer, billing data, or controlled before/after model run was used.

## Policy Arithmetic

| Implemented control | Derivation | Classification |
| --- | --- | --- |
| 10-minute vs 5-minute schedule | 6 vs 12 scheduled opportunities/hour; 50% fewer | Configuration comparison, excludes ad hoc checks |
| Initial vs continuation prompt caps | 6,000 vs 3,000 characters; 50% lower cap | Upper bounds, not observed usage |
| Batch size 2-4 | 1 Worker vs 2-4; 50%-75% fewer creations | Conditional arithmetic, not actual performance |
| Positive terminal wait | One call, at most 30,000ms per Run | Request limit, not transport latency |
| Actionable panel | Up to 8 rows / 4,000 characters | Default presentation budget |

Sources: [monitor policy](../scripts/monitor_policy.py), [wait policy](../scripts/wait_policy.py), [Packet builder](../scripts/build_context_packet.py), [panel renderer](../scripts/render_task_panel.py), and [Task schema](schemas/task.schema.json). A deterministic planner does not make the host Heartbeat model-free.

## Reproduce Privately

From the Skill directory:

```bash
PROJECT=/path/to/project
python3 scripts/measure_context_baseline.py \
  --tasks-dir "$PROJECT/docs/tasks" \
  --board "$PROJECT/docs/dispatch-board.md" \
  --public --output /tmp/pm-public-baseline.json
```

The published JSON is a dated snapshot, not a live dashboard. A changed project will yield different numbers. `--public --format markdown` produces a shareable aggregate table; ordinary output includes source paths and should stay private.

## Privacy Review

The public export constructs a new object from numeric fields and a fixed set of task-type labels. It does not copy arbitrary report fields, unknown type labels, paths, names, task/Worker IDs, titles, prompts, credentials, or session text. Templates/aliases are excluded before counting.

This revision reviewed maintained Markdown, examples, and skill UI metadata. It did not publish private agent definitions or raw session logs, delete local backups, rewrite Git history, or claim a full repository secret scan. Backup ignore rules prevent accidental new additions but cannot remove anything already tracked.

Public examples use fictional IDs/titles and generic areas such as API/WEB. Agent aliases resolve locally; model versions and private endpoints belong in local definitions, not public setup instructions. Aggregated counts can still be identifying in a small organization, so publication remains a user decision.

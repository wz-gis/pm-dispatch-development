# Task Panel

任务面板固定使用以下五列：

| 状态 | 任务 | 优先级 | 当前进展 | 下一步 |
| --- | --- | --- | --- | --- |
| 进行中 | BUG-041 最近诊断记录 | P1 | 已完成数据回填，自动测试通过 | 补 API/性能证据，再执行 L3/L4 |

- `任务` 只显示 `<id> <title>`；不重复优先级、Area 或完整 `display_name`。
- `当前进展` 只写已验证事实；`下一步` 只写一个动作或决策。
- 先排进行中和阻塞，再排待确认和待实施，最后排可选项；同组按 P0-P3。
- 主面板不展示 Owner、Worker、Run、Lease 或 Adapter；仅在用户要求或状态异常时增加“运行详情”。
- 不在表格前后复述字段含义，不使用卡片或逐任务长段落。
- 默认 `actionable` 视图最多 8 项、4000 字符；已验证和已关闭任务不进入默认视图。
- 已成功的 `RELEASE-*` 折叠到可见父任务，只有运行中、失败、漂移或独立查询时单列。

常用命令：

```bash
python3 scripts/render_task_panel.py --tasks-dir docs/tasks
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --view blocked
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --view waiting-user
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --view verified
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --task SPEC-031
python3 scripts/render_task_panel.py --tasks-dir docs/tasks --view all
```

支持 `actionable`、`blocked`、`waiting-user`、`verified`、`all` 五个视图；可用 `--limit` 和 `--max-chars` 覆盖默认预算。状态、排序、折叠和限额以脚本及快照测试为准。

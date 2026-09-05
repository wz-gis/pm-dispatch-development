# Closure And Terminal Report

After a Worker, Run, Attempt, or direct task reaches a terminal state, verify Task/Evidence with the Validator and proactively report the outcome. Heartbeat collection follows the same contract; "monitoring stopped" is not a closure report.

## Gate Outcomes

- `VERIFIED`: real acceptance evidence passes, with no open blocker.
- `L*_VERIFIED_MOCK`: PM explicitly accepted a mock fallback; Evidence records `mock_based` and `accepted_fallback`.
- `PARTIAL_VERIFIED`: some checks passed, with explicit remaining gaps.
- `ENV_BLOCKED`, `CONTRACT_BLOCKED`, `THREAD_BLOCKED`, `PM_BLOCKED`: matching Blockers exist in Task and Evidence.
- `CLOSED`: verified-like Evidence, `lifecycle.phase=archive`, `closure.status=closed`, and acceptance timestamps are present.

UI/L3 requires a Browser Artifact. API/L2 requires API, SQL, or a successful Command Artifact. SQL, migration, and release work require Upgrade or Release Artifacts. All triggered required/conditional quality checks must pass; skipped checks must be untriggered and explained.

## Report Fields

Use the user's language. Report the actual evidence level, never describe L2/L3 as L4. Include work actually performed, remaining gaps/blockers, environment limits, risks, required user actions, product/PM commits, and one next step. Never request or record a secret; describe the login or authorization the user must perform.

```text
<TASK_ID>: <status>; verified through <level>.
Passed: <key checks and evidence>.
Open: <gaps, blockers, or none>.
Your action: <one action, or none>.
Commits: product <commit/none>; PM <commit/none>.
Next: <one action, or none>.
```

# Fixed Worker Model Design

## Goal

Make every visible `codex-thread` worker use the exact model name `5.6 sol`. Keep task difficulty responsible only for the model tier and reasoning intensity.

## Behavior

- `direct` tasks do not create workers and keep `selected_model: null`.
- `single-worker`, `batch-worker`, and `full-dispatch` tasks set `dispatch.model_policy.selected_model` to `5.6 sol`.
- Every `codex-thread` run sets `runs[].selected_model` to `5.6 sol`.
- Difficulty continues to select the minimum tier: `simple -> fast`, `normal -> standard`, `hard -> reasoning`, and `critical -> reasoning|max`.
- Batch workers use the highest difficulty in the batch while keeping the fixed model.
- User model overrides are no longer allowed for visible workers. Tier escalation remains allowed.

## Enforcement

- The task Schema restricts worker `selected_model` values to `5.6 sol` and allows `null` only where no visible worker exists.
- The validator rejects a worker strategy whose model policy omits `5.6 sol` or names another model.
- The validator rejects a `codex-thread` run whose selected model is missing or differs from `5.6 sol`.
- Documentation and examples consistently show the fixed model and dynamic tier.

## Verification

- A worker fixture using `5.6 sol` passes validation.
- Worker fixtures with `selected_model: null` or another model fail validation.
- A direct fixture with `selected_model: null` continues to pass.
- JSON Schema parsing, Python compilation, skill validation, and `git diff --check` pass.

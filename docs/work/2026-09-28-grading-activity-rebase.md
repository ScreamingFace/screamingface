---
ticket: OME-1337
stack: screamingface-engine, screamingface
status: done
started: 2026-09-28
finished: 2026-09-28
---

# Rebase grading activity onto the current executor

## Intent
Resolve PR #1071 conflicts with main, as requested by the user.

## Planned changes
Preserve the new executor run-environment split and apply the PR activity default in `_run_env`. Replay all four existing commits without introducing new behavior.

## Test plan
Run both affected stack quality gates and the existing worker activity deployment tests. The rebase conflict is the initial failing integration signal.

## Acceptance
Clean rebase, passing checks, and updated PR branch with both changes preserved.

## Outcome
- Rebased all four PR commits onto main at `df6e9b92`.
- Resolved the sole conflict in `worker/supervisor.py`: `_run_env` defaults activity to `full`; `cold_child_env` retains ownership of the I/O budget.
- Range-diff confirms the other three commits are unchanged and the first differs only in the worker integration context.
- Both `run_gates.py screamingface-engine` and `run_gates.py screamingface` passed, including lint, formatting, types, full tests, coverage, layering, notebook checks, build and distribution validation.
- First Engine run: 4,466 passed; one removal-contract test failed on stale ignored bytecode in the old node-tier directory. Removed only those cache files and their empty directories; full rerun passed.
- Wisdom review: no new behavior, schema, public contract, dependencies, or test changes; preserves both upstream executor ownership and the reviewed activity policy.
- Rebased commits: `8a4a9d9b`, `0362ef00`, `4051d9e5`, `8c009082`.
- Deviations: used existing regression tests for this conflict-only integration; no new behavior required a new test.

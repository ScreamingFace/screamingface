---
ticket: OME-1557
stack: screamingface
status: done
started: 2026-10-09
finished: 2026-10-09
---

# Fusion quorum rollout and repr follow-up

## Intent

Apply the two user-approved nonblocking corrections from the PR #1340 review.

## Planned changes

- Fusion repr, appended repr regressions, README, and changelog.
- This spec, plan, and work ledger; update the existing PR description after validation.

## Test plan

- First demonstrate optional Model, Pipeline, and Fusion members print identically
  to required members; append tests distinguishing each pair.
- Run the full SDK gates including existing compact-repr and public-surface checks.
- Check the rollout wording against the URL4 scope fix already present in the PR.

## Acceptance

- Optional member policy appears in Fusion repr, while required members remain compact.
- The rollout note covers both patched URL4 execution and Engine reporting.

## Outcome

- **Actual files:** Fusion repr; appended tests in `test_fusion_quorum.py`;
  README and changelog; this spec, plan, and ledger. PR description updated at push.
- **Commits:** `fix(client): expose optional fusion members and clarify rollout`
  on parent `7eb4bc9e638687224136b6784a3b82ca8a082ee8`.
- **Gates:** `UV_OFFLINE=1 uv run .claude/scripts/run_gates.py screamingface --base HEAD`
  passed: append-only, lint, formatting, typecheck, full SDK coverage suite (95% floor),
  deterministic notebooks, package build, and distribution validation.
- **Regression evidence:** all three new repr cases failed before the change and
  passed afterward; the focused quorum/Recipe suite passed 54 tests.
- **Wisdom review:** reuse each optional Recipe's existing repr, preserving required
  members' compact names. No new public signatures, executable URL4 changes,
  dependencies, or schema changes. Rollout wording matches the existing runtime fix.
- **Deviations:** used an isolated disposable clone of the existing PR branch;
  this follow-up stays on the existing OME-1557 issue and PR. No previous assertions changed.


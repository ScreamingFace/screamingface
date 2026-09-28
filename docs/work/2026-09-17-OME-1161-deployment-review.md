---
ticket: OME-1161
stack: screamingface-engine
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1161 — Deployment review follow-up

## Intent

Honor explicit local activity settings without treating ambient environment values as caller overrides. Owner approved the PR 935 rebase, fixes and commit on 2026-09-17.

## Planned changes

- Rebase only deployment commits after 7de24afb onto origin/main; preserve merged plugin cleanup.
- config.py: retain activity-setting source provenance.
- local.py: explicit configured settings > injected env > process env > off, with effective settings synchronized.
- observation_plugins.py: reuse job_env.ACTIVITY_LEVEL.
- Append deployment regression coverage; preserve existing tests.
- Update shared spec/plan/task mirror and PR base.

## Test plan

- RED: supplied Settings loaded from ambient full must respect injected off/empty mapping; reverse precedence, process fallback and explicit constructor settings remain covered.
- Assert effective app settings match observer policy and invalid injected policy is rejected when no explicit override exists.
- Run focused activity/deployment tests in clean and ambient-full environments, then all Engine gates.

## Acceptance

- Activity cannot be enabled by an implicit ambient setting against injected off.
- Explicit Settings activity wins; unrelated supplied settings remain intact.
- Full gates pass and the rebased deployment-only PR targets main.

## Outcome

- **Actual files:** config.py, local.py, observation_plugins.py, appended deployment tests, shared spec/plan/task mirror and this ledger, as planned.
- **Commits:** rebased deployment commits a3614c5f and 278803dc onto 0c0abfcf; follow-up commit `fix(engine): preserve explicit activity policy provenance` (this commit).
- **Gates:** six regression failures reproduced before the fix; 30 deployment cases and all 46 focused activity/integration cases pass, including with ambient full. All Engine gates green (append-only tests, Ruff lint/format, Pyright, layering, full pytest/coverage). Helm lint and 112/112 chart-wiring checks pass.
- **Wisdom/confidence:** source provenance is a private boolean specific to activity constructor/copy overrides; no generic provenance framework, schema migration, or plugin/core coupling. Effective settings are copied, preserving caller state. Independent Standards and Spec reviews found no blockers. Existing tests unchanged.
- **Deviations:** none. Existing environment-sensitive test is fixed by corrected production behavior without modifying it. No Linear comments; worker-startup validation remains outside this focused local-policy fix.

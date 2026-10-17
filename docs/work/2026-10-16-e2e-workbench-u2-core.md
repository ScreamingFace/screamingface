---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress
started: 2026-10-16
finished:
---

# e2e-workbench-u2-core — notebooks driven by pytest, evidence by trace id (replay + local)

## Intent

Unit 2 of the e2e notebook workbench (epic OME-1636): `pytest tests/e2e/workbench` executes
generated, output-free notebooks against `replay` (keyless, CI) or `local` (`screamingface up` +
an inspect-capable Engine). A run passes only when the notebook's asserts hold and every reported
trace id is found in every required hop (engine, aigateway with `gateway_call_id`). Each run writes
a redacted evidence bundle.

## Planned changes

Per `docs/plan/2026-10-16-e2e-workbench-u2-core.md` (tasks 1–7) plus three review rounds:
`packages/screamingface/tests/e2e/workbench/**`, `tests/e2e/harness/trace_evidence.py`,
`tests/e2e/test_correlation_chain.py` (rung 3 uses the shared helper), the replay workflow, the
`just workbench` recipe. Also carries the unit 4 plan (`docs/plan/2026-10-17-e2e-workbench-u4-ui.md`)
and the OME-1637 close-out of the unit 1 ledger and task copy.

## Test plan

Workbench unit tests (runner, evidence, bundle, targets, builder, result checks, REQUIRE_ALL via
pytester); the real replay lane; the keyless local boot test.

## Acceptance

Replay lane green in CI with `REQUIRE_ALL=1` and the evidence artifact uploaded; local target boots
an Engine that lists ifeval; one paid local quickstart run recorded here before merge.

## Outcome

- **Rebuilt on main** after PR #1438 squash-merged: the unit 2 commits were cherry-picked onto
  `origin/main` (`637594595`); the workbench code is identical to the reviewed branch.
- **Gates (2026-10-17):** `pytest -n auto --cov` 4267 passed, 35 skipped, coverage 97.02%; ruff,
  format, pyright clean; `check_notebooks.py` ok. Real replay lane (`TEST_E2E=1`, `REQUIRE_ALL=1`,
  no keys): 75 passed, incl. `test_notebook[replay-quickstart]` and `test_local_boot`.
- **Not yet run:** the quickstart on the `local` target with a paid key (OpenRouter) or a Codex
  subscription — two Codex sign-in windows expired before approval.
- **Deviations:** location under `tests/e2e/workbench/` (spec §3); local target uses an
  inspect-capable `EngineProcess` beside `screamingface up`; deferred items listed in spec §3.4.1.

---
ticket: OME-1644
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
- **Deviations:** location under `tests/e2e/workbench/` (spec §3); local target uses an
  inspect-capable `EngineProcess` beside `screamingface up`; deferred items listed in spec §3.4.1.

## Paid local acceptance run (2026-10-21)

- **Run 1 (head `3ba94d3b3`) — FAIL, a real finding.** The notebook passed against live OpenRouter
  (`best_open_source` fusion, score 1.0, 0 cache hits) and the trace id was found in both hops, but
  the verdict failed: "9 aigateway lines lack gateway_call_id". The 9 lines were LiteLLM's stdout
  `print()` "Provider List: https://docs.litellm.ai/docs/providers" banner and its blank lines,
  captured by the runtime as `[gateway]` text inside the request window. They are not log records,
  so they cannot carry a call id; rung 3's own scope (OME-938) excludes such text. Replay never
  calls a provider, so it never showed this.
- **Fix:** the workbench call-id check now considers only gateway log records (lines with a level:
  `INFO:`, `WARNING:` …). An anonymous record inside the window still fails (test added).
- **Run 2 (fixed head) — PASS.** `test_notebook[local-quickstart] PASSED` in 73 s; trace
  `e859210b7065770008b0d5a1a619399e` found in engine (4 lines) and aigateway (7 lines), 0 anonymous
  gateway records, lifecycle scheduled + terminated both true, score 1.0, 0 cache hits. The key was
  read from the repo `.env` (`OPENROUTER_KEY` → `OPENROUTER_API_KEY`) and passed through the
  notebook's own `client.connect("openrouter", api_key=…)` path; its value appears nowhere in the
  bundle. Ports 9105/9106/9108 free afterwards.
- **Observation (follow-up, not a workbench defect):** the LiteLLM "Provider List" banner is printed
  when LiteLLM fails a provider lookup mid-request on the real path (likely a cost/model-map lookup
  for one of the OpenRouter models); worth a look in aigateway.

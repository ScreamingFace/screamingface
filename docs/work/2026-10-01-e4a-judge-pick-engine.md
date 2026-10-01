---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# e4a-judge-pick-engine — judge operators (label, scores, by_label, max_score) and the binding param

## Intent

OME-1289 (E4a) unit 8, engine half. A judge model reads the candidates and returns a label or one
score per member. The Fusion answer is the chosen member's own text, never the judge's prose. This
unit adds four built-in combine operators (`label@1`, `scores@1`, `by_label@1`, `max_score@1`) with
a strict judge-reply parser; a parse failure always raises `judge_reply_invalid`. It also makes the
model param `binding` attribution-only: the connector strips it before the gateway, so a judge call
on the same route as a member keeps its own attribution fingerprint (P2). A new golden harness for
fixtures in `fixtures/combine/flow/` serves units 8 to 10.

## Planned changes

- New: `combine/operators/judge.py`; modify `combine/builtins.py`.
- Modify: `world/request_parameters.py` (`OPERATION_BINDING_PARAM`, in `_INTERPRETED_PARAMS`).
- New fixtures: `tests/unit/fixtures/combine/flow/{label@1,scores@1,by_label@1,max_score@1}.json`.
- New tests: `combine_flow_support.py`, `combine_judge_scenarios.py`, `test_combine_judge.py`,
  `test_combine_flow_golden.py`, `test_combine_flow_isolation.py`,
  `test_combine_judge_determinism.py`, `test_combine_judge_world.py`,
  `test_operation_binding_param.py`.
- Not touched: `ports.py`, the unit 2 and 3 tests (OP-1 and FW-15 already accept later built-ins).

## Test plan

JG-1 label parser (fuzz) · JG-2 scores parser · JG-3 failure raises `judge_reply_invalid`, no prose ·
JG-4 by_label copies text · JG-5 tie goes to author order · scores from numeric values · scores args
and missing signal · flow golden (one exact-set disjointness check, the stage check, each case) ·
JG-8 evidence literal · OP-18 isolation · FW-3 hash seeds · P2 binding param · EV-H3 judge on a
member route · JG-9 provider failure codes · catalog lists the four ids.

## Acceptance

- All tests above pass; CHAR tests pass at once by design.
- Engine gate green; with append-only on there are no offenders.
- `repo` gate green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. New: `combine/operators/judge.py`; tests `combine_flow_support.py`,
  `combine_judge_scenarios.py`, `test_combine_judge.py`, `test_combine_flow_golden.py`,
  `test_combine_flow_isolation.py`, `test_combine_judge_determinism.py`,
  `test_combine_judge_world.py`, `test_operation_binding_param.py`; fixtures
  `fixtures/combine/flow/{label@1,scores@1,by_label@1,max_score@1}.json`. Modified:
  `combine/builtins.py`, `world/request_parameters.py`.
- **Commits:** 7539ee566 feat(engine): make the binding model param attribution-only;
  8f64d33a5 feat(engine): add the strict judge combine operators; 617d42b07 test(engine): run a
  judge Candidate end to end in the engine world.
- **TDD notes:** RED seen for the right reason (assertion, against a skeleton `judge.py` whose
  functions returned empty results): all 45 tests of `test_combine_judge.py` (JG-1 to JG-5, JG-3
  world-less, scores from values, args and missing signal, JG-8). OP-1 (unit 2) and the flow
  exact-set check were RED while the four built-ins were wired and their fixtures were missing; the
  fixtures then made both GREEN. P2: the `OPERATION_BINDING_PARAM` constant was added first, so the
  RED was the assertion (`binding` still in `model_params`); reverting only the `_INTERPRETED_PARAMS`
  entry makes both `test_binding_param_is_attribution_only` and the EV-H3 world test fail on the
  "no gateway body has `binding`" assertion (checked by hand). CHAR by design (pass at once): the 4
  fixture files' cases (the operators were implemented before the fixtures, and the hand-computed
  oracle matched), OP-18 isolation, the plugin-state walks, FW-3 hash seeds, the world tests
  (provider refusal, HTTP 400, prose from a judge model) and the catalog test.
- **Gates:** `run_gates.py screamingface-engine --base e4a-engine-wiring-evidence` (append-only on):
  no offenders, ALL GATES GREEN (ruff, format, pyright, check_layering, pytest with the 80 percent
  coverage floor). With `--skip-append-only`: ALL GATES GREEN. `repo`: ALL GATES GREEN.
- **Deviations:** the flow-golden test (`test_combine_flow_golden.py`) does NOT assert that top-level
  plus flow fixtures equal the built-in ids (spec step 8). It keeps the disjointness, stage, file
  count and file stem checks only; the exact-set check is OP-1's job (D-9). Extra tests beyond the spec table (all inside the listed files): a
  one-extra-character fuzz for the label parser, `huge-int`, `other-tag` and `empty-fence` score
  replies, a 64 KiB judge reply, a too_large label member, and a prose-from-a-judge-model world test.

## Review round 1 (coordinator: ACCEPT-WITH-FIXES)

- `scores@1.json` gained 9 hand-derived cases (whole-reply fence with outer whitespace, CRLF fence,
  spaced tag, no newline before the closing fence, `-0.0`, `1e-400`, judge mode with a too_large
  member, values mode with negative and decimal values, a voter with no value). Every hand
  derivation matched the code on the first run.
- The prose world test asserts `permanent is True` and exactly one judge call (no retry).
- Flow golden test: file count equals loaded fixtures, and each file stem equals its op id.
- `combine_flow_support.py`: no `__all__`; `judge_spec` takes the keyword-only `reducer`,
  `select_op` and `select_args` (defaults keep the old behavior).
- Dropped the duplicate walk-helper test. NBSP, ZWSP, fullwidth 2 and e-acute are written as escapes.
- JG-3 is one parametrized test (label and scores) with the log-line and no-recorded-call checks.
  The old no-call test ran inside a nested capture scope, so it could not fail; the new helper
  calls `CombineRoute` in the test's own scope, and a positive control records exactly one call.
- `request_parameters.py`: the `binding` explanation lives in the module docstring only.
- Scenario texts are numbered like their member ids; `returns` is typed `Literal`.
- Gates after this round: append-only run (vs `e4a-engine-wiring-evidence`) has no offenders and is ALL GATES GREEN; `--skip-append-only` and `repo` are ALL GATES GREEN.

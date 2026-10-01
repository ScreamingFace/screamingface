---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# e4a-rank-concat-engine — rank (top_k) and concat (join, all) combine operators

## Intent

OME-1289 (E4a) unit 10, engine half. Rank keeps the top k original member texts in score order and
hands the next stage one selection JSON (`{"selected": [{"id", "text"}, ...]}`). Concat joins every
member text in author order with visible boundaries and no model call. This unit adds three built-in
combine operators (`top_k@1`, `join@1`, `all@1`) in `combine/operators/selection.py`. Both reducers
make `kind = selection` evidence. `top_k@1` reads the scores that `scores@1` (unit 8) makes, from a
judge or from numeric field values.

## Planned changes

- New: `combine/operators/selection.py`; modify `combine/builtins.py` (one import name, one
  `*selection.OPERATORS` line).
- New fixtures: `tests/unit/fixtures/combine/flow/{top_k@1,join@1,all@1}.json`.
- New tests: `test_combine_selection.py`, `test_combine_selection_determinism.py` (+ support
  `combine_selection_scenarios.py`), `test_combine_rank_world.py`.
- Not touched: `ports.py`, `spec.py`, `endpoint.py`, any unit 2, 3 or 8 test or support module.
- Deferred (remaining work): `test_sdk_flow_catalog_fixture.py` (spec 6.3 step 14), because the SDK
  file `packages/screamingface/tests/_combine_flow_fixtures.py` does not exist yet. Add it after
  linearizing onto the unit 9 engine and the SDK halves.

## Test plan

RK-3/OP-14 top_k by judge scores, originals in rank order · RK-5 top_k by field · RK-7 fewer usable
than k is `combine_no_votes` · RK-8 cut tie goes to author order · CC-1 join order, labels,
separator · CC-4 separator collision · CC-6 empty member keeps its slot · CC-7 joined text over the
cap · CC-2 no network call · CC-5 empty separator · args bounds (k, label, separator) · goldens ·
FW-3 hash seeds · RK-9/RK-4 world test (judge output kept, next stage sees the selection only) ·
catalog lists the three ids · OP-1 exact set (RED until each fixture exists).

## Acceptance

- All tests above pass; CHAR tests pass at once by design.
- Engine gate green; with append-only on there are no offenders.
- `repo` gate green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. New: `combine/operators/selection.py`; tests
  `combine_selection_support.py` (spec builders, an addition to the plan),
  `combine_selection_scenarios.py`, `test_combine_selection.py`,
  `test_combine_selection_determinism.py`, `test_combine_rank_world.py`; fixtures
  `fixtures/combine/flow/{top_k@1,join@1,all@1}.json`. Modified: `combine/builtins.py` (the import
  became a parenthesized list because the single line would pass 100 characters).
- **Commits:** 8904f5cb4 feat(engine): add the rank and concat combine operators (top_k, join, all);
  6041046fb test(engine): run rank and concat end to end and across hash seeds; plus the ledger
  commit that closes this file.
- **TDD notes:** a skeleton `selection.py` (empty selections, wired in `builtins.py`) came first.
  RED seen for the right reason: all 37 tests of `test_combine_selection.py` failed on assertions
  or `DID NOT RAISE` (RK-3, RK-5, RK-7, RK-8, CC-1, CC-4, CC-6, CC-7, CC-2, CC-5, the args cases);
  OP-1 (unit 2, rglob exact set) was RED with the three ids `all@1`, `join@1`, `top_k@1` missing
  and went GREEN when the three fixtures landed. CHAR by design (pass at once): the three golden
  fixtures (hand-computed oracle matched the operators), FW-3 hash seeds, the two world tests
  (rank Pipeline, concat Pipeline) and the catalog test.
- **Gates:** `run_gates.py screamingface-engine --base e4a-judge-pick-engine` (append-only on): no
  offenders, ALL GATES GREEN (ruff, format, pyright, check_layering, pytest with the 80 percent
  coverage floor). With `--skip-append-only`: ALL GATES GREEN. `repo`: ALL GATES GREEN.
- **Deviations:** none from the spec. Extras inside the listed areas: `top_k` sorts with
  `sorted(..., reverse=True)` and not a negated key, because `-Decimal` rounds to 28 digits (a test
  pins exact comparison beyond 28 digits). A world test with `$model_1`, quotes and newlines in
  member text shows url4 does not re-expand a substituted value.
- **Remaining work:** `test_sdk_flow_catalog_fixture.py` (spec 6.3 step 14, the SDK drift guard)
  is deferred: `packages/screamingface/tests/_combine_flow_fixtures.py` does not exist yet. Add it
  after the unit 9 engine and the SDK halves are linearized.

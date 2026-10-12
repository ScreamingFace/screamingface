---
ticket: OME-1588
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
- **Deviations:** from the spec text, four, none changes behavior it pins:
  1. `top_k` sorts with `sorted(..., reverse=True)` and not a negated key (`-Decimal` rounds to the
     28-digit default context); a test pins exact comparison beyond 28 digits.
  2. The `builtins.py` import is a parenthesized multi-line list (the single line is 101 chars).
  3. A new support module `tests/unit/combine_selection_support.py` (spec builders), not in the spec.
  4. The CC-5 test is `test_join_rejects_bad_args` (9 cases), plus `test_top_k_rejects_bad_args`.
  Review round 1 changes: the collision check `_has_extra_separator` counts overlapping matches
  (the first version, `joined.split(separator) != parts`, missed an overlap that ends inside the
  next part); two right-overlap cases were added to `join@1.json` and the CC-4 test (RED first, 4
  failures), the CC-4 test asserts the exact joined text for every case, and a `too_large` member
  with the top judge score is kept whole (CHAR).

- **Per-test table** (CHAR = passes at once by design). Tests are in `test_combine_selection.py`
  unless noted.

| Id | Test | RED | GREEN |
|---|---|---|---|
| RK-3 / OP-14 | `test_top_k_by_judge_scores_passes_k_originals_in_rank_order` | yes | yes |
| RK-3 | `test_top_k_copies_member_text_byte_for_byte_with_canonical_escaping` | yes | yes |
| RK-5 | `test_top_k_by_field` | yes | yes |
| OP-14 | `test_top_k_compares_scores_exactly_beyond_28_digits` | yes | yes |
| RK-7 | `test_fewer_usable_than_k_fails_with_combine_no_votes`, `test_k_above_the_judged_member_count_fails_with_combine_no_votes` | yes | yes |
| RK-8 | `test_cut_tie_goes_to_author_order`, `test_a_tie_above_the_cut_keeps_author_order_inside_the_kept_group`, `test_k_equal_to_the_member_count_has_no_cut_tie` | yes | yes |
| RK-9 (too_large) | `test_a_too_large_member_with_the_top_score_is_kept_whole` | no (CHAR) | yes |
| args | `test_top_k_rejects_bad_args`, `test_top_k_rejects_an_extra_arg_and_accepts_the_bounds`, `test_top_k_without_scores_is_a_spec_error` | yes | yes |
| CC-1 | `test_concat_joins_in_author_order_with_labels_and_separator`, `test_concat_uses_the_given_separator` | yes | yes |
| CC-4 | `test_separator_collision_is_flagged` (5 cases; the two overlap cases were RED on the split version) | yes | yes |
| CC-6 | `test_empty_member_keeps_its_slot`, `test_a_too_large_member_is_still_joined` | yes | yes |
| CC-7 | `test_joined_text_over_cap_fails` | yes | yes |
| CC-2 | `test_concat_makes_no_network_call` | yes | yes |
| CC-5 | `test_join_rejects_bad_args`, `test_join_accepts_a_separator_of_exactly_1024_characters`, `test_all_without_a_joined_text_is_a_spec_error` | yes | yes |
| OP-1 | `test_combine_operators_golden.py::test_golden_outputs_match_for_every_registered_operator` | yes | yes |
| goldens | `test_combine_flow_golden.py::test_flow_golden_case_matches` (top_k, join, all) | CHAR (2 join cases RED in round 1) | yes |
| FW-3 | `test_combine_selection_determinism.py` (3 tests) | CHAR | yes |
| RK-9 / RK-4 | `test_combine_rank_world.py::test_rank_keeps_judge_output_and_next_stage_sees_selection_only` | CHAR | yes |
| CC-1 / CC-2 world | `test_combine_rank_world.py::test_concat_makes_no_model_call_and_next_stage_sees_the_joined_text_only` | CHAR | yes |
| catalog | `test_combine_rank_world.py::test_catalog_lists_the_selection_operators` | CHAR | yes |

- **Remaining work:** `test_sdk_flow_catalog_fixture.py` (spec 6.3 step 14, the SDK drift guard)
  is deferred: `packages/screamingface/tests/_combine_flow_fixtures.py` does not exist yet. Add it
  after the unit 9 engine and the SDK halves are linearized.

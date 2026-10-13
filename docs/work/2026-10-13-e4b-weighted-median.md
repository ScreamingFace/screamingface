---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine, screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-13
finished:
---

# e4b-weighted-median — weighted median reducer and sf.Median(weights=...) (E4b unit 4)

## Intent

A benchmark author can give more say to trusted members in a robust number combine. The engine
gets `weighted_median@1`. It sorts the members with a usable weight by value. It returns the value
where the running weight first reaches half the total weight. At exactly half, it returns the mean
of the two neighbors, so equal weights give the same result as `median@1`. A member with a missing
or non-positive weight is dropped. A dropped member never wins `nearest` (Q2, P9). `sf.Median` and
`sf.Reduce("median", ...)` accept `weights=` and compile to it. A median without weights keeps its
url4 bytes. PRD: `docs/spec/2026-10-13-e4b-combine-extensions/prd/weighted-median.md` (WM#1-15) and
`prd/catalog-and-schema.md` (CS#1-2).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/combine/operators/reduce.py` — `weighted_median`, descriptor, op id in `_signal_weight` / `_decimal` messages.
- `apps/screamingface-engine/src/screamingface_engine/combine/spec.py` — `REDUCER_RULES["median"].weights = "optional"`.
- `packages/screamingface/src/screamingface/reducer.py` — `Median(weights=...)`, rebuild, repr, member count check.
- `packages/screamingface/src/screamingface/blocks.py` — median block option `weights`, plan, rebuild.
- New tests: `apps/screamingface-engine/tests/unit/test_combine_weighted_median.py`,
  `apps/screamingface-engine/tests/unit/test_combine_weighted_median_run.py`,
  `packages/screamingface/tests/test_weighted_median.py`,
  `packages/screamingface/tests/test_weighted_median_url4_fixture.py`; appended test in
  `apps/screamingface-engine/tests/unit/test_rest_operators.py`.
- New data: `apps/screamingface-engine/tests/unit/fixtures/combine/weighted_median@1.json`,
  `apps/screamingface-engine/tests/unit/data/combine_contract/weighted_median_confidence_candidate.url4`.
- Pinned edits (owner approval): `packages/screamingface/tests/test_signal_weighted_vote.py`
  (`test_median_rejects_signal_weights`), `packages/screamingface/tests/_combine_flow_fixtures.py`
  (`FLOW_OPERATOR_IDS`), `packages/screamingface/tests/public_surface_snapshot.json`; NOT
  pre-approved: `apps/screamingface-engine/tests/unit/test_combine_spec.py`
  (`test_only_the_vote_reducer_takes_weights`, `test_weights_accept_a_signal_ref_and_reject_unknown_keys`).
- Docs: `packages/screamingface/README.md`, `packages/screamingface/CHANGELOG.md`.

## Test plan

- CHAR: WM#1 (unweighted median bytes, repr, to_python), WM#2 (even count median).
- RED, engine: WM#3 (past half → 60), WM#4 (exactly half → 40), WM#5 (nearest never picks the
  dropped member), WM#6 (equal weights = median, property), WM#7 (drop unusable weights → 90),
  WM#8 (no participant → no_votes), WM#9 (no spec weights → combine_spec_invalid), WM#9b (median@1
  ignores weights → 20), WM#10 (duplicates order, property; 25), WM#11 (one participant → 7.5),
  WM#12 (golden), CS#1 (catalog lists weighted_median@1), CS#2 (SDK catalog equals the builtins).
- RED, SDK: WM#13 (named form compiles weighted_median@1), WM#14 (block form accepts weights and
  round-trips), S-1 (named round trip), S-2 (bad weights refused), S-3 (fixture drift guard).
- RED, integration: WM#15 (engine runs the SDK median block weighted by `field:confidence` → member_4).

## Acceptance

- All rows above pass; the unweighted median compiles to the same bytes as before.
- `GET /v1/operators` lists `weighted_median@1` (reduce); `FLOW_OPERATOR_IDS` equals the builtins.
- No new failure code; no schema id change; no schema snapshot change.
- Gates green for screamingface-engine, screamingface and repo, except the append-only check,
  which lists only the pinned files above until the owner approves them.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">; parent checks P-1..P-10 results

## RED evidence (commit A)

Run: engine focused set (§5.2) and SDK focused set (§5.2), before any GREEN code.

- Engine: 23 failed, 461 passed.
- SDK: 6 failed, 121 passed.
- CHAR rows pass: WM#1 (`test_sdk_median_without_weights_compiles_the_same_bytes`) and WM#2
  (`test_median_even_count_is_the_mean_of_the_middle_two`).

| Row | Result | Reason |
|---|---|---|
| WM#3-7, WM#10, WM#11 | fail | `NotImplementedError: weighted_median@1 lands in the GREEN commit` |
| WM#8 | fail | `NotImplementedError` (no `NoVotes` yet) |
| WM#9 | fail | `NotImplementedError` (no `SpecInvalid` yet) |
| WM#9b | fail | `SpecInvalid: reducer median forbids weights` |
| WM#12 | fail | `LookupError: no plugin module lists the combine operator 'weighted_median@1'` |
| WM#13 | fail | `TypeError: weights apply to Vote only` |
| WM#14 | fail | `ValueError: sf.Reduce('median') does not take option 'weights'; it takes extract` |
| WM#15 | fail | `AssertionError: the url4 fixture is missing: run write_fixture() in the SDK` |
| CS#1 | fail | `assert 'weighted_median@1' in {...}` (not registered) |
| CS#2 | fail | `test_sdk_flow_catalog_names_exactly_the_builtins` (engine catalog lacks the id) |
| S-1 | fail | `TypeError: weights apply to Vote only` |
| S-2 | fail | `TypeError: weights apply to Vote only` |
| S-3 | fail | `AssertionError: the url4 fixture is missing` path check |
| Property WM#6, WM#10 | fail | `NotImplementedError` (inside the seeded loop) |

Side effects in existing tests (caused by the RED fixture file; not edited, see Deviations):
`test_combine_operators_golden.py::test_every_fixture_file_names_a_module_operator_of_its_stage`,
`test_every_builtin_operator_has_exactly_one_golden_fixture`, and the seven parametrized
`test_golden_case_matches_for_every_module_operator[weighted_median@1-...]` cases fail with
`LookupError` or a set mismatch. They pass after commit B registers the operator.

## Parent checks (P-1..P-10, on `e4b-mean`)

- P-1 `Reduction.participants` present (`combine/ports.py:298`). OK.
- P-2 `nearest@1` reads `participants` (`combine/operators/select.py:87-88`). OK.
- P-3 `_signal_weight(answer, op_id="weighted_mode@1")`. OK, no change needed.
- P-4 `_decimal(answer, op_id="median@1")`. OK, no change needed.
- P-5 `_reduction_view` renders only `tally` and `statistic`. OK, so no `participants` key in the golden expects.
- P-6 `FLOW_OPERATOR_IDS` had 39 ids; `mean@1` and `weighted_mean@1` present. Now 40.
- P-7 `Mean` calls `_refuse_judge_signal(selected, "Mean", _MEAN_SIGNAL_USE)`. OK.
- P-8 Not checked in this commit. The property tests use a seeded `random.Random` loop (no `hypothesis`).
- P-9 README "Combine recipes" present (line 722). CHANGELOG bullet not checked yet (commit C).
- P-10 `test_rest_operators.py` checks by key and against the builtins list. No exact reduce-id set. OK.

## Deviations (commit A)

- The RED stub is in `reduce.py`, not registered in `OPERATORS`, as the spec says.
- The SDK has no stub, as the spec says. Pyright reports 10 type errors in the SDK RED tests
  (`weights` is not a parameter of `Median` yet). The pre-commit hooks run ruff only, so the commit
  hooks pass. The pyright gate runs after GREEN.
- Commit A applies the two `test_combine_spec.py` edits (spec §4.3 items 5-6). The spec says they
  are needed only after the `REDUCER_RULES["median"]` change (commit B). They follow the commit
  plan as written. Owner approval is still needed (NOT pre-approved).
- The fixture file makes four existing golden tests in `test_combine_operators_golden.py` fail in
  commit A (listed above). The spec does not list them. They are not edited here. The orchestrator
  must decide.

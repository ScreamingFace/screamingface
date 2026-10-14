---
ticket: OME-1590
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 9S -- sf.Pick, sf.Merge, their block forms and argmax

## Intent

Rebase `e4a-pick-merge-sdk` onto `e4a-judge-pick-sdk` (tip `36084a4a9`). Port the old 9S logic
(`sf.Pick`, `sf.Merge`, `sf.FieldRule`, the projection and writer seams) onto the reducer plan. Add the
block forms `sf.Reduce('pick_field')` and `sf.Reduce('merge')`, and add argmax as
`sf.Pick(by_signal=..., order=...)` with its block form `sf.Reduce('argmax')`. Row: BK#4 (pick_field,
merge, argmax). Orchestrator follow-ups: 9E (a `values@1` path over 256 characters is refused before
spend), 10E F3 (one `order` in both argmax steps), F12 (an accounting key emits `sources`).

Old base `933c28c1c`. Old tip `64ca4e323` (the reference for the port: `git show 64ca4e323:<path>`).
The replayed commit `1c1c9224e` is empty after the rebase (see Notes).

Second rebase (orchestrator): the parent `e4a-judge-pick-sdk` moved from `36084a4a9` to `155a71ae6` (the 8S
review fix round). `git rebase --onto e4a-judge-pick-sdk 36084a4a9 e4a-pick-merge-sdk` ran without a
conflict. It left one broken import (see N2).

## Planned changes

- A: this ledger.
- B: port Pick, Merge and the writer seams onto the reducer plan (F1-F3). Snapshot and CHANGELOG.
- C: `FieldRule` hashable and the `pick_field` and `merge` block forms (F4, F5).
- D: argmax: `sf.Pick(by_signal=...)`, `accounting_signal` seam, `sf.Reduce('argmax')` (F6-F10, F12).
- E: engine-world contract test of an SDK-written argmax-by-cost Fusion.
- F: CHANGELOG and README.
- G: results.
- Fix (after the second rebase): a Pick or Merge url4 decode refusal is `cannot rebuild` (N6).

## Test plan

Rows 1-13 of the unit spec (`gap-unit9s-pick.md` section 3). The RED/GREEN table is in Outcome.

## Notes

### Rebase (section 2.0)

Pre-check (`git diff --stat 933c28c1c e4a-judge-pick-sdk -- <src, STU/test_signal_key_conformance.py,
ET/test_combine_writer_template_world.py>`): `fields.py` and `test_combine_writer_template_world.py` are
not in the parent. No STOP.

Rebase: `git rebase --onto e4a-judge-pick-sdk 933c28c1c e4a-pick-merge-sdk`. Replayed commits (new sha):
`921f48eb2` -> `25111ea73`, `be1272e1e` -> `d84c902b4`, `476220e8f` -> `a81cd8f03`, `1c1c9224e` -> dropped
(empty), `7cc4203f0` -> `2cdb8b3ec`, `2f94e33c8` -> `1350018a0`, `64ca4e323` -> `9a4384baf`.

| Stop | Commit | Conflicted files | Resolution |
|---|---|---|---|
| 1 | `921f48eb2` | `CHANGELOG.md`, `README.md`, `reducer.py`, `_evaluation/reducer_signals.py`, `STU/test_signal_key_conformance.py` (add/add) | The 7 F1 src files, the snapshot and the conformance test: `git checkout HEAD --`. CHANGELOG and README: the parent text, plus the 9S bullet and the 9S "Pick and merge JSON fields" section after it. The new files (`fields.py`, 3 tests) are theirs. |
| 2 | `476220e8f` | `__init__.py`, `reducer_signals.py`, `topology.py`, `judge.py`, `reducer.py`, `url4.py`, conformance | The same `git checkout HEAD --` of the F1 files. |
| 3 | `1c1c9224e` | conformance test | HEAD. The commit became empty and git dropped it. Its content (the conformance tests) is ported in Commit B. |

The commits `7cc4203f0`, `2f94e33c8` and `64ca4e323` applied without a stop (they touch only new files, the
ledger and the README).

After the rebase the src diffstat versus the parent (`e4a-judge-pick-sdk`) is only the new file
`fields.py` (553 lines). The engine test `test_combine_writer_template_world.py` (166 lines) is new.

Post-rebase red set: `import screamingface` works (the parent `__init__.py` does not import `fields`).
`tests/test_merge_writer_compile.py` and `tests/test_pick_merge_url4_round_trip.py` are collection errors
(`ImportError: cannot import name '_signal_field'` / `'_writer_key'` from `topology`).
`tests/test_pick_merge_reducers.py` collects, and its tests fail with `AttributeError: module 'screamingface'
has no attribute 'Pick'` (the spec expected a collection error; the cause is the same, the missing port).
`ET/test_combine_writer_template_world.py` is green (1 passed, engine only), as the spec requires.

### Flags F1-F12 (from the spec)

F1 rebase strategy (restore, then port in Commit B). F2 conformance test: HEAD at the stop, append 9S's
three tests in Commit B. F3 `_ModelSignal.field`, `_ReducerPlan` for Merge and `_ProjectionReducer`.
F4 `FieldRule` hashable, `fields._FieldRules`. F5 `pick_field` block builds `Pick`. F6 argmax is
`Pick(by_signal=, order=)` with the same `order` in both steps. F7 `_ReducerPlan.reads` and `_read_signal`.
F8 `Pick(by_signal=sf.signal('score:judge'))` is refused. F9 the `Pick` signature. F10 `Pick._from_spec`
dispatches on the reduce op. F11 `fields.py` joins the workflow `paths:`. F12 unit 4's "does not compile
yet" test drops argmax and pick_field.

## Outcome

Commits (after the second rebase): A `docs(work): add the e4a gap-closure unit 9S ledger`, B `refactor(sdk):
port sf.Pick, sf.Merge and the writer seams onto the reducer plan`, C `feat(sdk): make sf.FieldRule
hashable and compile sf.Reduce('pick_field') and sf.Reduce('merge') as their named forms`, D `feat(sdk): pick
the member with the best named signal with sf.Pick(by_signal=..., order=...)`, E `test(sdk,engine): run an
SDK-written argmax-by-cost Fusion in the engine world`, F `docs(sdk): document sf.Pick by signal and the pick
and merge block forms`, fix `fix(sdk): report a Pick or Merge url4 decode refusal as cannot rebuild, not as
constructor text`, G this ledger.

### RED / GREEN

| Row | Test | RED | GREEN |
|---|---|---|---|
| B (port) | all replayed 9S tests | post-rebase red set (Notes): 2 collection `ImportError`s, `AttributeError` in `test_pick_merge_reducers.py` | Commit B |
| B#1 | `test_pick_merge_plan.py::test_pick_merge_and_projection_build_a_reducer_plan` | assertion `0 == 1` (stub `Merge._plan()` with no writer calls) | Commit B |
| B#2 | guards: replayed 9S tests, `ET/test_combine_writer_template_world.py`, 8S tests, `test_pick_specs`, `test_merge_without_model_fields_is_one_combine_call`, the three conformance tests | none (guards pass at once) | Commit B |
| C#3 | `test_pick_merge_blocks.py::test_every_op_table_row_matches_its_named_form` (8 params) | `ValueError ... does not compile in this SDK version yet` | Commit C |
| C#4 | `test_pick_and_merge_blocks_canonical_equality_hash_and_errors`, `test_the_block_forms_are_registered` | assertion (`equals=7` vs `"7"`, empty form registry) | Commit C |
| C (GE21) | `test_field_rule_params_are_compared_by_type_and_value` | assertion `True`-param rule `!=` `1`-param rule (stub hash `0`, generated `eq`) | Commit C |
| C (GE21) | `test_field_rule_is_hashable_and_hash_equal_for_equal_rules` | none after the stub (RED was the unhashable `TypeError` of the old `None` hash; the stub hash was added to keep the other rows on assertions) | Commit C |
| C#5 | `test_reducer_recovery_preference.py::test_a_pick_or_merge_url4_is_recovered_as_the_named_class_for_both_forms` | not run RED apart (the block compile of C#3 is its RED) | Commit C |
| C (in place) | `test_blocks_reduce.py` (merge fields TypeError, `_one_per_row` merge row, round-trip rows, F12 for pick_field), `test_pick_merge_reducers.py:78` | probed: with the two forms unregistered, 6 rows failed | Commit C |
| D#6 | `test_pick_by_signal.py::test_pick_by_signal_compiles_by_signal_and_best_holder`, `test_the_same_order_goes_into_both_steps` (10E F3 pin, 12 params incl. the block) | assertion `'max' == 'min'` (stub plan with a fixed order) | Commit D |
| D#7 | `test_pick_by_signal_validation` | assertion on the message (stub text), `DID NOT RAISE` | Commit D |
| D#8 | `test_argmax_by_accounting_signal_emits_sources`, `test_accounting_signal_reads_a_pick_and_still_reads_the_weights` | assertion: no `sources` (stub plan without `reads`) | Commit D |
| D#9 | `test_argmax_block_matches_pick` (6 params), `test_argmax_block_canonical_form` | `ValueError ... does not compile in this SDK version yet` | Commit D |
| D#10 | round trip, BK#8 recovery, 11 tampering rows | `DID NOT RAISE`, assertion on the order | Commit D |
| D#11 | `test_blocks_reduce.py` F12 (argmax and pick_field compile with `flow_operators()`) | covered by the D#9 `ValueError` | Commit D |
| E#12 | `test_argmax_contract_fixture.py` | assertion: fixture file missing | `write_fixture()` |
| E#13 | `ET/test_argmax_contract.py` | none (CHAR; passes at once; `signal` is not None) | Commit E |
| 9E note | `a * 257` rows of `test_pick_merge_reducers.py` and the pick_field row of `test_pick_and_merge_blocks_...` | none (guard: `_check_pick_field` already refuses a path over 256 characters; the block reaches it through `Pick`) | replayed |
| Fix | 8 rows in `test_pick_merge_url4_round_trip.py` (Pick path, blank equals, Merge name, normalize, fields, empty writer prompt) | assertion: the constructor text instead of `cannot rebuild` | Fix commit |

Gates (base `e4a-judge-pick-sdk`, tip `155a71ae6`):

- `screamingface` (append-only on): offenders are `tests/public_surface_snapshot.json`,
  `tests/test_blocks_reduce.py` and `tests/unit/test_signal_key_conformance.py` (the in-place stack tests of
  rule 2 and the snapshot).
- `screamingface --skip-append-only`: ALL GATES GREEN (ruff, format, pyright, pytest with coverage, notebooks,
  build, distribution). Coverage 97% (gate 95%): 3140 passed, 26 skipped.
- `screamingface-engine --skip-append-only`: ALL GATES GREEN.
- `repo`: ALL GATES GREEN.

### Notes on the work (deviations and findings)

- **N1 (post-rebase red set).** The spec expects collection errors in the three new test files. Two files
  (`test_merge_writer_compile.py`, `test_pick_merge_url4_round_trip.py`) were collection errors. The third
  (`test_pick_merge_reducers.py`) collects, and its tests fail with `AttributeError: module 'screamingface'
  has no attribute 'Pick'`. The cause is the same (the missing port). The engine test was green.
- **N2 (second rebase).** The parent moved `_append_combine` from a module function into a
  `_CandidateCompiler` method. `_projection_source` imported the old function, so the package failed to
  import after the rebase (git applied the hunk without a conflict). Fixed in Commit B (amended, then the
  later commits replayed) so that every commit imports.
- **N3 (explicit `normalize=None`).** `sf.Reduce('pick_field', ..., normalize=None)` still raises (the unit 4
  `_check_normalize` accepts the five names only). The tests leave the key out for `None`.
- **N4 (option order).** The canonical `pick_field` options follow the op-table row order: `field`,
  `normalize` (when set), `equals`; or `field`, `order`.
- **N5 (stricter recovery).** `Pick._from_spec` and `Merge._rebuild` end with `_require_steps(spec,
  <named>._plan().steps, ...)`, so a spec the plan would not write is refused whole. Spec bytes of every
  literal Pick and Merge are unchanged (the replayed tests pin them).
- **N6 (decode rule, orchestrator message).** A public constructor that runs on url4 data goes through
  `fields._decoded(name, build, ...)`. A `TypeError` or `ValueError` becomes `cannot rebuild`, never
  constructor text. Deliberate decode messages (`_INVALID_SIGNALS`, `_UNSUPPORTED_WRITER`) are unchanged.
  Three replayed rows that pinned constructor text now pin `cannot rebuild`.
- **N7 (GE21).** `FieldRule.__eq__` and `__hash__` use one typed key. `_FieldRules` and `Merge` compare
  through it. `Pick.equals` is stored as text, so it has no bool/int/float ambiguity.
- **N8 (engine world harness).** Review fix: `tests/unit/_signal_world.py` holds the gateway body and
  `run_candidate(candidate, models, cache)`. `test_signal_vote_replay.py` and `test_argmax_contract.py` use
  it, and 10S reuses it.
- **N9 (in-place tests).** `test_merge_writer_compile.py` builds the new combine-evidence wire (`member_id`,
  `reason`, `signals`) and `_MergeWithSignals` overrides `_plan()`. `test_pick_merge_url4_round_trip.py` reads
  `_plan().kind`.
- **N10 (F11).** The workflow `paths:` lists name the engine `fields.py` (the `spec.py` path was already there).
- **N11 (gate runs).** `test_client_run.py` interrupt tests did not fail in the final runs.
- **N12 (review fix round).** `_decoded` moved to `reducer.py` (chained with `from exc`, also used by
  `Vote._from_spec_parts`). `_read_signal` asserts the GE5 one-signal rule. The `_BlockForm` docstring allows
  lazy imports. `test_argmax_contract.py` asserts `sources:` in the fixture.

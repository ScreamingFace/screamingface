---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 8S -- sf.Judge, sf.Reduce('judge') and the judge-weighted vote

## Intent

Rebase `e4a-judge-pick-sdk` onto `e4a-rank-concat-engine` (tip `eb138aa9b`). Port the old 8S logic
(`sf.Judge` and the reducer signal seams) onto the unit 4-7 reducer plan. Add the block form
`sf.Reduce('judge', judge=...)`, and add `sf.Vote(weights=sf.signal('score:judge'), judge=...)`.
Rows: BK#4 (judge row), SR#11 (SDK part).

Old base `6aeaf4ce4`. Old tip `933c28c1c` (the reference for the port: `git show 933c28c1c:<path>`).

## Planned changes

- A: this ledger.
- B: port `Judge` and the signal seams onto `_ReducerPlan.signal_calls` (F2).
- C: `_CONTEXT_SIGNALS` reads the signal keys when `sources` follows them (F8).
- D: `Judge.__hash__` (F4) and the `sf.Reduce('judge', judge=..., rubric=...)` block form (F3).
- E: `sf.Vote(..., judge=...)` and `sf.Reduce('weighted', ..., judge=...)` with the pairing rule (F5, F6).
- F: engine-world contract test of an SDK-written judge-weighted vote.
- G: CHANGELOG and README.
- H: results.

## Test plan

Rows 1-16 of the unit spec (`gap-unit8s-judge.md` section 3). The RED/GREEN table is in Outcome.

## Notes

### Rebase (section 2.0)

Pre-check (`git diff --stat 6aeaf4ce4 e4a-rank-concat-engine -- <the 9 files + CHANGELOG, README,
snapshot>`): overlap in CHANGELOG, README, `__init__.py`, `candidate.py`, `reducer.py`, `url4.py` and the
snapshot. `topology.py`, `_evaluation/url4.py`, `_operation_bindings.py`, `accounting.py` and
`_candidate_policy.py` did not change in the parent. No replayed 8S test or new 8S file existed in the
parent.

Rebase: `git rebase --onto e4a-rank-concat-engine 6aeaf4ce4 e4a-judge-pick-sdk`. Replayed commits:
`313e1a678` -> `fa0cccf12`, `a47ead6a1` -> `5a24d9a35`, `933c28c1c` -> `8c4438745`.

Second rebase (orchestrator message): the parent moved from `eb138aa9b` to `f4858fcfe` (3 engine-only
review-fix commits, no SDK file). `git rebase --onto e4a-rank-concat-engine eb138aa9b e4a-judge-pick-sdk`
ran without a conflict, after Commit B.

| Stop | Commit | Conflicted files | Resolution |
|---|---|---|---|
| 1 | `313e1a678` | `CHANGELOG.md`, `_evaluation/candidate.py`, `reducer.py`, `url4.py` | The three src files: `git checkout HEAD --`. CHANGELOG: kept the parent text, inserted the 8S `sf.Judge` bullet after the weights bullet. |
| 2 | `933c28c1c` | `CHANGELOG.md`, `_evaluation/candidate.py`, `url4.py` (`reducer.py` auto-merged) | The same. `reducer.py` was also restored with `git checkout HEAD --`, because a half-applied hunk is wrong on the new plan. |

`README.md`, `__init__.py`, `_candidate_policy.py`, `topology.py`, `_evaluation/url4.py`,
`_operation_bindings.py`, `accounting.py` and the snapshot merged without a conflict (the parent did not
change the 6 non-overlapping src files). Their merged result equals the old 8S hunks, so Commit B keeps
them and does not restore-then-reapply them (same bytes).

Post-rebase red set: `import screamingface` fails (`ImportError: cannot import name '_ModelSignal' from
'screamingface.reducer'`, from `judge.py`). Every SDK test is a collection error (159 errors). This is the
rebase artifact the spec predicts. Commit B fixes it.

### Flags F1-F14 (from the spec)

F1 rebase strategy. F2 `signal_calls` is the last field of `_ReducerPlan`; no `Reducer._signals()` hook.
F3 `judge=` takes an `sf.Judge`; `rubric=` replaces its rubric and is never stored (errata for block-api
2.2). F4 `Judge` is hashable. F5 unit 7's compile-time `score:judge` refusal is replaced by a
construction-time pairing rule (a replacement, not a bare removal; flag for the orchestrator). F6 `judge`
is an optional option of the `weighted` row (errata for block-api 2.2). F7 one `_fusion_context` builder,
with `sources=` by keyword. F8 `_CONTEXT_SIGNALS` allows a `sources` key after `signals`. F9 one
`url4._rebuilt_reducer(spec, signals)`. F10 named modules register block forms; lazy `Judge` imports in
`blocks.py` and `reducer.py`. F11 `FLOW_OPERATOR_IDS` equals the Engine built-ins (37 ids, below). F12
`test_judge_report.py` builds the unit 1 wire. F13 `FIELD_PATH` comes from `screamingface._signals`.
F14 judge calls never enter `_ResolvedRecipe.calls`.

F11 engine output (`sorted((d.id, d.stage) for d in BUILTIN_OPERATORS)`, 37 entries): all@1 select,
best_holder@1 select, boxed@1 extract, built@1 select, by_field@1 select, by_label@1 select, by_signal@1
reduce, field_rules@1 reduce, filter@1 reduce, first_holder@1 select, identity@1 normalize, inspect_aime@1
extract, inspect_number@1 extract, inspect_numeric@1 normalize, join@1 reduce, json_field@1 extract,
json_object@1 extract, kept@1 select, label@1 reduce, last_line@1 extract, last_number@1 extract,
max_score@1 select, max_weight_holder@1 select, median@1 reduce, mode@1 reduce, nearest@1 select,
numeric@1 normalize, project_field@1 reduce, regex@1 extract, scores@1 reduce, set@1 normalize, text@1
normalize, top_k@1 select, value@1 select, values@1 reduce, weighted_mode@1 reduce, whole@1 extract.

Engine facts (built): the Engine reads `score:judge` strictly. A spec that reads it without a judge is
`combine_spec_invalid`. A malformed, non-finite or oversize reply is `judge_reply_invalid`. A judge-weighted
vote has `evidence.judge is None`; the scores are in `members[].signals["score:judge"]` and in `weight`
(errata GE29, GE30).

`ST/test_judge_reducer.py` is not on main (`git cat-file -e 4eca379d1:...` fails), so the spec's in-place
change at line 109 (F4) is allowed.

## Notes on the work (deviations and findings)

- **N1 (F1, restore of the 9 files).** Six of the nine pre-existing src files (`__init__.py`,
  `_candidate_policy.py`, `topology.py`, `_evaluation/url4.py`, `_operation_bindings.py`, `accounting.py`)
  merged without a conflict, and their merged result equals the old 8S hunks. Commit B kept them and
  ported only the three conflicted files (`reducer.py`, `candidate.py`, `url4.py`) onto the plan. The
  resulting tree is the same as restore-then-reapply.
- **N2 (F9, error text).** `url4._rebuilt_reducer` re-raises the named class's error when both the named
  class and `sf.Reduce` refuse (spec F9 step 3). For a pure rule this changes the text of a refusal from
  the `sf.Reduce` "cannot rebuild" to the named class's own error. Unit 5's
  `test_benchmark_extract_op_in_a_hand_edited_url4_is_refused` pinned the old text; it is edited in place
  (`match="benchmark"`, Commit B). The tamper tests of 8S pin the named text and pass.
- **N3 (`_Call.context`).** `_Call` gets a new required field `context`. Unit 5's `_call_with` helper in
  `test_reducer_recovery_preference.py` builds a `_Call` by hand, so it passes `context=""` (Commit B).
- **N4 (pure-rule test).** `test_a_pure_rule_reducer_refuses_signals` (replayed 8S test) used a plain
  `Vote`. A `Vote` now reads a scores judge call (F5), so the test uses `sf.Median` for "a pure rule
  refuses signals", and a new test pins that a `Vote` refuses a label-judge call (Commit E, in place).
- **N5 (`Vote._from_spec`).** A `score:judge` spec with no judge call raises `_cannot_rebuild("vote")`
  explicitly in `Vote._from_spec_parts` (the spec says the pairing rule "becomes the url4 cannot rebuild
  error"; without it F9 step 3 would re-raise the pairing text).
- **N6 (`_next_binding("synthesis")`).** The `synthesis` branch has no production caller (the old 8S code
  had none either; `_fusion` still counts directly). A unit test covers it. Left as in 8S.
- **N7 (pyright on tests).** The gate runs pyright on the tests too. The new test files were fixed for it
  (folded into Commits D and E).
- **N8 (sandbox).** The SDK tests that start a local HTTP/WebSocket server need the unsandboxed shell
  (local sockets). The SDK gate and the engine tests ran unsandboxed.
- **N9 (SDK gate, known red, not from 8S).** `test_client_run.py::test_interrupting_concurrent_candidates_stops_every_active_engine_run`
  and `::test_concurrent_interrupt_deletes_every_active_engine_capability` fail when `test_client_protocol.py`
  runs before them (two files: `JSONDecodeError` in `_decoded_result_body`; the reconnect loops of the two
  100 s tests are still alive). Both pass alone (`14 passed`). The same two fail on the parent tip
  `f4858fcfe` (SDK source archived from the branch, same venv, same two files: `2 failed, 58 passed`). They
  are an order-dependent failure of the reconnect transport, not of 8S. The orchestrator must decide.

## Outcome

Commits (after the second rebase): A `docs(work): add the e4a gap-closure unit 8S ledger`, B `refactor(sdk):
port sf.Judge and the reducer signal seams onto the reducer plan`, C `fix(sdk): read the combine context
signal keys when sources follow them`, D `feat(sdk): make sf.Judge a hashable value and compile
sf.Reduce('judge', judge=...) as it`, E `feat(sdk): weight sf.Vote by judge scores with judge=sf.Judge(...,
returns='scores')`, F `test(sdk,engine): run an SDK-written judge-weighted vote in the engine world`, G
`docs(sdk): document sf.Judge, its block form and judge-weighted votes`, H this ledger.

### RED / GREEN

| Row | Test | RED | GREEN |
|---|---|---|---|
| B (port) | all replayed 8S tests | post-rebase red set: `ImportError _ModelSignal`, 159 collection errors (rebase artifact) | Commit B |
| B#1 | `test_judge_plan.py::test_judge_builds_a_reducer_plan` | assertion: `() == (_ModelSignal(...),)` (stub `_plan` without `signal_calls`) | Commit B |
| B#2 | replayed 8S tests green | (no RED: the post-rebase set above) | Commit B |
| B#3 | guards: `test_reducer_characterization`, `test_combine_contract_fixture`, `test_vote_median_contract_fixtures`, `test_weighted_vote_contract_fixture`, `test_signal_vote_contract_fixture`, `test_samples_contract_fixture`; `combine_contract` diff empty | none (guards pass at once) | Commit B |
| C#4 | `test_reducer_signals.py::test_context_signal_keys_survive_a_sources_key` | assertion `() == ('judge',)` | Commit C |
| D#5 | `test_judge_blocks.py::test_every_op_table_row_matches_its_named_form` (8 params) | unit 4 `ValueError ... arrives with sf.Judge` | Commit D |
| D#6 | `test_judge_blocks.py` (canonical form, hash, errors, form registry) and `test_judge_reducer.py:109` | same `ValueError`; hash stub assertion `0 != 0` | Commit D |
| D#7 | `test_blocks_reduce.py` (BK#7 judge rows, `_one_per_row`, round trip) | collection `ValueError` (the module builds the judge row at import) | Commit D |
| D#8 | `test_reducer_recovery_preference.py::test_a_judge_url4_is_recovered_as_the_named_judge_for_both_forms` | same `ValueError` | Commit D |
| E#9 | `test_judge_weighted_vote.py::test_vote_judge_scores_compile_the_judge_call_and_signals` (+ nested F14) | unit 7 `ValueError ... needs a judge on the same reducer` | Commit E |
| E#10 | `test_score_judge_weights_and_a_vote_judge_pair_up` (vote and block) and unit 7 `test_score_judge_weights_wait_for_the_judge` | `DID NOT RAISE ValueError` | Commit E |
| E#11 | `test_weighted_judge_block_matches_vote` (6 params) | unit 7 `ValueError` | Commit E |
| E#12 | round trip, regex block form, 3 tamperings, topology without signals, rebuild refusals | unit 7 `ValueError` | Commit E |
| E#13 | `test_vote_repr_python_and_equality_carry_the_judge` | assertion on `repr` | Commit E |
| F#14 | `test_judge_vote_contract_fixture.py` | assertion: fixture file missing | `write_fixture()` |
| F#15 | `ET/test_judge_vote_contract.py` | none (CHAR; passes at once). Separator pinned: U+2028 after `judge-template@1 returns=scores` | Commit F |

### Gates (base `e4a-rank-concat-engine`, tip `f4858fcfe`)

- `screamingface` (append-only on): offenders are `tests/public_surface_snapshot.json`,
  `test_blocks_reduce.py`, `test_reducer_recovery_preference.py`, `test_signal_weighted_vote.py` (the
  in-place stack tests of rule 2 and the snapshot).
- `screamingface --skip-append-only`: ruff, format, pyright green; coverage 96.88% (gate 95%); pytest:
  only the two known failures of N9.
- `screamingface-engine --skip-append-only`: ALL GATES GREEN.
- `repo`: ALL GATES GREEN.

### Errata (for block-api 2.2)

- F3: `sf.Reduce('judge', judge=<sf.Judge>[, rubric=...])`. `rubric` replaces the rubric of that judge and
  is never stored.
- F5: the construction-time pairing rule replaces unit 7's compile-time `score:judge` refusal.
- F6: `judge` is an optional option of the `weighted` row.

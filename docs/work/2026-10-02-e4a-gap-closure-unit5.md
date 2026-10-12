---
ticket: OME-1583
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 5 -- sf.Vote / sf.Median on the reducer plan, extract="benchmark", recovery

## Intent

Fold the Vote/Median part of the E4a gap-closure into `e4a-vote-median`, on top of the unit 4
reducer slot (`e4a-sdk-reducer-slot`, `c7447d7cb`). `sf.Vote` and `sf.Median` build a `_ReducerPlan`
(the seam they share with `sf.Reduce`). `sf.Vote(extract="benchmark")` groups answers the way the
selected benchmark grades them: the rule is read from the benchmark resource the SDK already fetches,
resolved at compile time before any spend, and pinned in the url4. A url4 reducer is recovered as
its named class when that class accepts the spec exactly, else as `sf.Reduce`. The old ledger
`docs/work/2026-10-01-e4a-vote-median.md` stays unchanged.

## Planned changes

- Rebase `e4a-vote-median` onto `e4a-sdk-reducer-slot` (this commit's ledger records the stops).
- `reducer.py`: `Vote`/`Median` use `_plan()`; `_ReducerPlan.benchmark_rule`; `BENCHMARK_EXTRACT`; the
  `_DefaultNormalize` sentinel (F5).
- `_evaluation/answer_rule.py` (new): `_AnswerRule`, `_BenchmarkAnswerRule`, `decode_answer_rule`,
  `resolve_benchmark_rule`. `operators.py`: `serves`, `is_pinned_operator_id`.
- `blocks.py`: `NAMED_EXTRACT_RULES`, `_answer_steps`; keywords in every `_Steps(...)` (F13).
- Compile threading: `benchmark.py`, `compilation.py`, `candidate.py`, `combine_spec.py`, `runner.py`
  (one comment).
- `url4.py`: `_reducer_from_call` prefers the named class, falls back to `sf.Reduce` (F7).
- Tests, test data, the Engine test repairs, the workflow path filter (F14), CHANGELOG and README.

## Test plan

A: this ledger. B: BK#2 (+ BK#1 seam guards). C: Engine repair, no RED. D: BK#8. E: BK#3, BK#4
(guards). F: decode (rows 7-8). G: GP#11, BK#10. H: GP#15, GP#9, GP#10, GP#12, GP#14, BK#4 benchmark
rows. I: AR#10, AR#11, RT#4, RT#1 (no RED, by design). J: CHAR Engine run of the benchmark-rule
spec. K: docs. L: this ledger closed.

## Rebase record (spec 2.0)

### Pre-check (read-only, `git diff --stat b6336d237 e4a-sdk-reducer-slot -- <unit 5 paths>`)

Overlap: `CHANGELOG.md`, `__init__.py`, `reducer.py`, `public_surface_snapshot.json` (expected), and
four new files in `apps/screamingface-engine/tests/unit/inspect/` (unit 3's own files, a directory
level overlap only; unit 5 touches none of them). No overlap with `README.md`, `_combine_contract.py`,
`test_vote_median*.py`, `data/combine_contract/`, `test_combine_vote_median.py`,
`test_combine_reducer_candidates.py`. No surprise.

### Stops

1. `961239d1b` (feat: add sf.Vote and sf.Median). `CHANGELOG.md` conflict: kept all of unit 4's
   reducer-slot text and put unit 5's Vote/Median bullet first. `reducer.py` conflict: took unit 4's
   file through `_REDUCER_CLASSES`, then unit 5's block verbatim. Not restored: `_reducer_class`
   (unit 4 removed it; no caller). The `STAGES` import the spec lists was not needed at this stop
   (the first commit's block has its own `_STEP_STAGES`); it arrived by itself when stop 2 replayed
   the tightening commit, which uses `STAGES`. `__init__.py` merged by git. Snapshot regenerated with
   `UPDATE_SURFACE_SNAPSHOT=1` (diff against unit 4: only `Median` and `Vote`).
2. `7323f57e2` (fix: tighten recovery ...). `CHANGELOG.md` conflict in the reducer-slot bullet only:
   kept unit 4's text, dropped unit 5's edit of that bullet (Commit K rewrites the Vote bullet).

`git log --oneline e4a-sdk-reducer-slot..HEAD` shows the four replayed commits; the merge base is
`c7447d7cb` (the unit 4 tip).

### Red set after the rebase (before Commit B)

The replayed commits are red until Commit B. That is a rebase artifact (unit 4 made `_plan`
abstract; `Vote`/`Median` still implement `_reducer`/`_kind`/`_steps`).

SDK (`uv run --directory packages/screamingface pytest -q`, 6m54s): 64 failed, 2426 passed.

- `tests/test_vote_median.py` and `tests/test_vote_median_contract_fixtures.py`: collection error
  (`TypeError: Can't instantiate abstract class`; a module-level `sf.Vote(...)`). These two files
  were ignored for the full run.
- `tests/test_blocks_reduce.py::test_reduce_to_python_round_trips`: 62 rows. All plurality and median
  rows (S1: abstract `_plan`), and also the weighted, `field` and `regex` rows. The weighted/arg rows
  fail because `Vote._from_spec` refuses them and `_reducer_from_call` does not fall back (F7); the
  spec named only the plurality and median rows, but the cause is the same F7/S2 witness.
- `tests/test_client_run.py::test_interrupting_concurrent_candidates_stops_every_active_engine_run`
  and `::test_concurrent_interrupt_deletes_every_active_engine_capability`: `websocket_disconnected`
  under load (a second pytest process ran at the same time). Both pass alone (`-k interrupt`,
  2 passed). Not part of the red set; not related to this unit.

Engine (`uv run --directory apps/screamingface-engine pytest -q tests/unit`): 3 failed, 5869 passed.
Exactly the spec's list (F8 S3, S4):

- `test_combine_vote_median.py::test_empty_extracts_do_not_vote_and_are_reported`
- `test_combine_vote_median.py::test_median_skips_non_numeric_members`
- `test_combine_reducer_candidates.py::test_no_votes_fails_case_with_combine_no_votes`

F2 verified: `git grep -n answer_rule apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py`
shows `metadata["answer_rule"] = self.answer_rule.as_block()` inside `Benchmark._metadata()` (line 321).

## Notes

### Results

Commits (conventional, no `Co-Authored-By`): A ledger, B plan port, C Engine repair, D recovery,
E guards, F decode, G Vote guards, H resolution, I Answers/trace, J Engine char, K docs, L this.

Gates (from the worktree, `--base e4a-sdk-reducer-slot`):

- `screamingface` WITHOUT `--skip-append-only`: red, exactly the two expected offenders.
  `tests/public_surface_snapshot.json` (regenerated by `UPDATE_SURFACE_SNAPSHOT=1`, only `Median` and
  `Vote` added) and `tests/test_blocks_reduce.py` (the BK#8 in-place edit of
  `test_reduce_to_python_round_trips`, F8 S2).
- `screamingface --skip-append-only`: ALL GATES GREEN (ruff, format, pyright, pytest with
  `--cov-fail-under=95`, notebooks, build, distribution). Coverage 97% (`TOTAL 11931 396`); 2596
  passed, 26 skipped. `_evaluation/answer_rule.py` is 100% (it is absent from the skip-covered report).
- `screamingface-engine --skip-append-only`: ALL GATES GREEN.
- `repo`: ALL GATES GREEN (append-only test check vs HEAD included).

Byte checks: `git diff e4a-sdk-reducer-slot -- tests/public_surface_snapshot.json` shows only
`Median` and `Vote` (F5, and `test_public_surface.py` passes unchanged after Commit G).
`vote_candidate.url4` and `model_synthesizer_candidate.url4` are byte-unchanged (the writer drops the
end-of-file newline the repo hook adds, so they were restored from git); `reducer_specs.json` gained
only `vote_benchmark_gsm8k_3`. Unit 4's `report.v1` goldens are unchanged.

### RED / GREEN per row

| Row | Commit | RED evidence | GREEN |
|---|---|---|---|
| BK#2 plan port | B | `AssertionError: Vote._steps is replaced by _plan()` (stub `_plan()` kept `_steps`) | `_plan()` on Vote and Median, `_reducer`/`_kind`/`_steps` deleted |
| BK#1 CHAR (seam guards) | B | none by design: `test_vote_compiles_to_pinned_spec`, `test_engine_vote_median_fixtures_match_the_sdk_compiler` green on the stub and after the port | same |
| Engine repair (F8 S3, S4) | C | none by design (repair; the three red Engine tests turned green) | n/a |
| BK#8 recovery | D | the code's own `ValueError: ... vote spec this SDK version cannot rebuild` on the regex, field and weighted rows (3 rows here, 20 in `test_reduce_to_python_round_trips`) | `_reducer_from_call` suppresses a named refusal and falls back to `sf.Reduce` |
| BK#3, BK#4 | E | none by design (the seam makes the pairs equal) | n/a |
| rows 7-8 decode | F | `None == _AnswerRule(...)`; `DID NOT RAISE PlanningError` (stub `decode_answer_rule` returned None) | `decode_answer_rule`, `is_pinned_operator_id`, `_BenchmarkResource.answer_rule` |
| GP#11, BK#10 | G | `DID NOT RAISE ValueError`; `unknown extract operator 'benchmark'`; `'text' is None` | sentinel, plan field, `resolve_benchmark_rule` (None branch) |
| GP#15, GP#9, GP#10, GP#12, BK#4 benchmark rows | H | the code's own `extract='benchmark' needs a benchmark` (after a `benchmark_rule` signature stub on `compile_candidate`) | resolver branches, `serves`, compile threading |
| GP#14 | H | red only because the first evaluation of its setup raised; a guard once GP#9 is green | n/a |
| AR#10, AR#11, RT#4, RT#1 | I | none by design (unit 4's join and trace; RT#1 golden written once by `write_golden()`) | n/a |
| Engine char of the benchmark-rule spec | J | SDK drift guard red (`Right contains 1 more item`), then `write_fixtures()`; the Engine test passes at once (GP-4 held) | n/a |

### F1-F14 and errata

- F1 (errata for the orchestrator): BK#14 (`sf.Reduce` Fusion warns on duplicate members) moved to
  unit 6. Not done here.
- F2: verified. `answer_rule` is in `Benchmark._metadata()` (`definition.py:321`); decoded from the
  benchmark resource, no extra request (GP#9 asserts exactly one `/v1/benchmarks/<id>`, no list call).
- F3: resolved inside `compile_evaluation` at the plan seam; `runner.py` got one comment in each twin.
- F4: `_ReducerPlan.benchmark_rule`, `blocks._answer_steps`; unit 4's BK#10 test still passes.
- F5: `_DefaultNormalize` sentinel; `test_public_surface.py` passes unchanged after Commit G.
- F6: `sf.Median(extract="benchmark")` and `benchmark@1` raise at construction.
- F7: the named class wins only when its own `_from_spec` succeeds.
- F8: S1 Commit B, S2 Commit D, S3 and S4 Commit C, S5 Commit K.
- F9: `_combine_contract` re-exports `engine_operators`; `ENGINE_OPERATOR_NAMES` is derived from
  `ENGINE_OPERATOR_IDS`; `PRE_INSPECT_OPERATOR_NAMES` keeps the old list.
- F10 (errata): the url4 depends on the rule's operators, so aime24 == aime25 != gsm8k (GP#15).
- F11 (errata): RT#1 is the report.v1 golden of a real run; RT#4 is the trace order and `trace_dict()`.
- F12 (errata): BK#1 at this unit is the two existing guards; the golden-contract file arrives in
  unit 11.
- F13 (errata): unit 4 shipped keyword `_Steps(...)` calls everywhere (`_median_plan` included), so
  no fix to `blocks.py` was needed. BK#2 and BK#4 would catch a positional bug.
- F14: the workflow path filter gets `apps/screamingface-engine/tests/unit/fixtures/combine/**` in
  both lists.

### Deviations and notes

- The rebase red set also held the weighted, `field` and `regex` rows of
  `test_reduce_to_python_round_trips` (62 rows, not only plurality and median); same F7/S2 cause.
- Two `test_client_run.py` interrupt tests failed once under load and pass alone. Not related.
- The benchmark-extract row of the refusal test (`benchmark@1` in a hand-edited url4 gives
  "cannot rebuild") moved from Commit D to Commit G: before G, `Vote` accepts `benchmark@1`.
- `_vote_run_fixtures.py` is built across F (resource), H (Engine, transport, `spec_of`) and I
  (`operation_wire`, `vote_case`), not in one commit.
- GP#10 and GP#12 run on the sync `sf.Client`; GP#10 also has the async twin (`sf.AsyncClient`).
- `json`, `field` and `regex` have no arg-less Vote form; `json_object@1` arrives in 9E (BK#4 note).
- Not done by design (section 4): BK#14, weights on Vote, `sf.Extract` into Vote, `answer_rule` on
  `discovery.Benchmark`, any Engine source change, the D-10 stage check in `_from_spec`.

### PRD row to test name

The spec names one test per row; three rows were split, and the names changed.

| Row | Tests |
|---|---|
| BK#4 | `test_every_plurality_row_matches_vote`, `test_every_median_row_matches_median`, `test_benchmark_rows_match_their_named_form` (`test_vote_median_blocks.py`) |
| GP#11 | `test_benchmark_extract_with_normalize_raises`, `test_benchmark_extract_takes_no_version_and_no_median`, `test_benchmark_vote_value_semantics` (`test_benchmark_answer_rule.py`) |
| AR#11 | `test_pipeline_member_text_is_its_final_operation_output` (a), `test_vote_inside_a_pipeline_answers_only_for_its_own_combine_step` (b) (`test_vote_answers_trace.py`) |
| BK#8 | `test_recovered_spec_prefers_named_class_else_reduce`, `test_named_refusal_falls_back_and_an_unrebuildable_spec_still_refuses`, `test_benchmark_extract_op_in_a_hand_edited_url4_is_refused` (`bare` and `benchmark@1`) |

### Known gap (next to D-10)

`Vote._from_spec`, `Median._from_spec` and `Reduce._from_spec` compare the reduce and select ops, and
Median's normalize op, by name only (`_op_name`). A url4 that carries `mode@2` is rebuilt as the
named form, and a recompile re-pins `mode` to the newest version the Engine serves. This is the same
shape as D-10 (no stage check in `_from_spec`). Not fixed in this unit.

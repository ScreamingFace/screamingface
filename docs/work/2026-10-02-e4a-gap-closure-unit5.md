---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
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
   (unit 4 removed it; no caller). Not added: `from screamingface._evaluation.operators import STAGES`
   (the spec says to keep it, but unit 5's block never used it; it would be an unused import. The
   block has its own `_STEP_STAGES`). `__init__.py` merged by git. Snapshot regenerated with
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

NOTES_PLACEHOLDER

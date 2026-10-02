---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
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
`313e1a678` -> `fbe164b43`, `a47ead6a1` -> `e8c2a121c`, `933c28c1c` -> `1bf901ffa`.

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

## Outcome

In progress.

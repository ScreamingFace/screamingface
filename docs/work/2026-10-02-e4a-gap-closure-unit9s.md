---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
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

## Planned changes

- A: this ledger.
- B: port Pick, Merge and the writer seams onto the reducer plan (F1-F3). Snapshot and CHANGELOG.
- C: `FieldRule` hashable and the `pick_field` and `merge` block forms (F4, F5).
- D: argmax: `sf.Pick(by_signal=...)`, `accounting_signal` seam, `sf.Reduce('argmax')` (F6-F10, F12).
- E: engine-world contract test of an SDK-written argmax-by-cost Fusion.
- F: CHANGELOG and README.
- G: results.

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

(filled in Commit G)

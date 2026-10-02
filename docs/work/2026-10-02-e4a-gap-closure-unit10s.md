---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
---

# e4a-gap-closure unit 10S -- sf.Rank by signal, sf.Concat, sf.Filter and the Fusion block form

## Intent

Rebase `e4a-rank-concat-sdk` onto `e4a-pick-merge-sdk` (tip `38bfe3b75`). Port the old 10S logic
(`sf.Rank`, `sf.Concat`, the three selection compile checks) onto the reducer plan. Add
`sf.Rank(k, by_signal=..., order=...)`, the block forms `top_k`, `concat` and `filter`, the new
`sf.Filter` with signal comparisons, and the Fusion recipe rewrite
(`Pipeline([Fusion(m, Reduce("context")), S, ...])` to `Pipeline([Fusion(m, S), ...])`). Rows: BK#4
(top_k, concat, filter), SR#9 (rank), FL#6-9, FR#1-12. Orchestrator amendments: (a) GE21 typed keys,
(b) the decode rule (`_cannot_rebuild`, never constructor text), (c) 10E F3 same `order` in both
Rank steps, (d) 10E F12 accounting key emits `sources`, (e) 10E F7 docstring, (f) 10E F6 filter
evidence score.

Old base `64ca4e323`. Old tip `877f17a26` (the reference for the port: `git show 877f17a26:<path>`).

## Planned changes

- A: this ledger.
- B: port Rank, Concat and the selection checks onto the reducer plan (F1-F3, F14). Snapshot, CHANGELOG.
- C: Fusion url4 goldens for every README and public-docs example (FR#1, FR#2). They come before G.
- D: `sf.Rank(k, by_signal=..., order=...)` and the `top_k` block (SR#9, BK#4).
- E: the `concat` block (BK#4).
- F: `sf.Filter`, the signal comparisons and the `filter` block (FL#6, FL#7, FL#9, BK#4).
- G: the Fusion recipe rewrite (FR#3-12).
- H: engine-world contract test of an SDK-written filter-then-model pipeline (FL#8).
- I: CHANGELOG and README.
- J: results.

## Test plan

Rows 1-29 of the unit spec (`gap-unit10s-rank.md` section 3). The RED/GREEN table is in Outcome.

## Notes

### Rebase (section 2.0)

Pre-check: `selection.py` (SDK) and `ET/test_sdk_flow_catalog_fixture.py` are absent in the parent
(the engine has its own `operators/selection.py`; that is a different file). No STOP.

Rebase: `git rebase --onto e4a-pick-merge-sdk 64ca4e323 e4a-rank-concat-sdk`. Replayed commits (new sha):
`40164ad66` -> `23041e026`, `686ee8690` -> `e12841ef8`, `218c6334b` -> `f039b20a9`, `ff4961ad4` ->
`167b08937`, `61164ca71` -> `2a51beaa2`, `d3ed377c6` -> `ac408bb2a`, `877f17a26` -> `7e0ff17e5`.

| Stop | Commit | Conflicted files | Resolution |
|---|---|---|---|
| 1 | `686ee8690` | `_evaluation/candidate.py` | HEAD (`git checkout HEAD --`). The replayed commit keeps only the new test file `test_selection_compile_checks.py`. |
| 2 | `218c6334b` | `CHANGELOG.md` | The parent text plus the Rank/Concat bullet, put after the Pick/Merge bullet (the unit order of `877f17a26`). `README.md` merged without a stop. |
| 3 | `d3ed377c6` | `fields.py`, `reducer.py` | HEAD. `selection.py` and the two replayed test edits are kept. |
| 4 | `877f17a26` | `CHANGELOG.md` | HEAD text, with the Rank bullet replaced by the `877f17a26` wording (names the operators). |

The commit `40164ad66` (first) applied without a stop; its edits to `reducer.py` and `candidate.py`
are not in the result. Pre-existing src files that differ from the parent after the rebase: only
`__init__.py` (+3 lines: the `Rank` and `Concat` import and export). `candidate.py`, `fields.py` and
`reducer.py` are equal to the parent (no stale hunk, verified with `git diff e4a-pick-merge-sdk HEAD`).

Src diffstat versus the parent: new `selection.py` (195 lines), `__init__.py` +3, README +51, CHANGELOG
+2, snapshot +21. New tests: `test_rank_concat_reducers.py` (286), `test_rank_concat_url4_round_trip.py`
(240), `test_selection_compile_checks.py` (154), engine `test_sdk_flow_catalog_fixture.py` (41).

Post-rebase red set: `import screamingface` fails (`ImportError: cannot import name '_field_path' from
'screamingface.reducer'`: `selection.py` imports the old `_field_path`). So EVERY SDK test is red, wider
than the spec's "three collection errors" (the spec said "possibly every reducer compile"; here the whole
package import breaks, because `__init__.py` imports `selection`). Commit A therefore does not import; the
tree is restored in Commit B. This is the recorded rebase artifact (F1).
`ET/test_sdk_flow_catalog_fixture.py` is GREEN (1 passed), as the spec requires.

### Flags F1-F14 (from the spec)

See `gap-unit10s-rank.md` section 1. Outcome lists the ones that needed a decision.

## Outcome

(filled in Commit J)

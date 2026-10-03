---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
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

### Second rebase (orchestrator)

The parent moved from `38bfe3b75` to `7d1fc0a83` (the 9S review fix round: `reducer._decoded`, the
shared `_signal_world.run_candidate`). `git rebase --onto e4a-pick-merge-sdk 38bfe3b75 e4a-rank-concat-sdk`
ran when only commits A, B and C existed. One stop: `fields.py` (import list, the parent's `_decoded`
and this unit's `_field_path`); both kept. The stale-hunk check (`git diff e4a-pick-merge-sdk HEAD`) shows
only intended edits.

### Order and deviations

- Commit order: A, B, C, G, decode fix, D, E, F, H, I, J. The orchestrator asked for the Fusion
  characterization and rewrite first (C before G is the hard rule). G needs nothing from D-F.
- Extra commit (not in the spec): `fix(sdk): report a Rank or Concat url4 decode refusal as cannot rebuild,
  not as constructor text` (amendment (b)). Four tamper rows pinned constructor text and were changed in
  place to `cannot rebuild` (RED first).
- Rule 7: the Rank (D) and Filter (F) commits carry their snapshot and CHANGELOG line; I adds the rest.
- `rewrite_fusion_recipe` returns the SAME object when nothing changes, and collapses a Pipeline to its
  one stage only when a pair was lowered. A recipe without a `context` block is therefore never rebuilt, so
  no existing Fusion can change by one byte (the unnamed one-stage `Pipeline(["x"])` stays a Pipeline).
- `Signal.__eq__`/`__ne__`/ordering return `Any` (a predicate, not a bool) instead of `# type: ignore[override]` (F5); the `-> Any` return keeps the numpy-style override legal for pyright, and an AIDEV-NOTE in `_signals.py` records that `1 in [s]` raises `TypeError` (F6).
- `1` and `1.0` thresholds are one predicate (the value is stored as a float, so equal values compile to
  equal bytes); `True` is distinct from both (typed key, GE21).
- The Engine's `filter@1` regex form reads the member's ORIGINAL text, never the extracted value
  (`operators/signals.py`). `extract=` only decides which members can vote. The Filter docstring, README and
  CHANGELOG say so (F7 of the spec implies the extract feeds the regex; the code wins).
- The Engine world test records the gateway requests through `run_candidate(..., on_request=...)` (review fix round; first built with a `monkeypatch` of `_gateway`).
- The 9S test `ST/test_blocks_reduce.py` `argmax` line (`unknown reduce operator 'by_signal'`) became a
  compile assertion, because F9 puts `by_signal@1` and `best_holder@1` in the fixture catalog.

### Flags F1-F14 (from the spec)

F1 restore then port (B). F2 `_ResolvedRecipe.selection` set from `plan.kind` with `_selection_label`.
F3 `_field_path` in `reducer.py`. F4 Rank signature and plans (D). F5/F6 `Signal` operators and
`_Comparison` in `_signals.py` (F). F7 `sf.Filter` (F). F8 `"filter"` in `_ReducerName`. F9 four ids in
`ENGINE_OPERATOR_IDS` and `rglob` in unit 5's test; **flag: it still lacks the 13 judge, pick, merge, rank
and concat ids (the full set is `FLOW_OPERATOR_IDS`)**. F10 block forms registered in `selection.py`;
`_OpRow.reserved` deleted. F11 named-S limit documented. F12 `compile_evaluation` names from the rewritten
recipe (**flag for the orchestrator**). F13 `Reducer._compiles_to_combine`. F14 workflow paths (B).

Verified in G: both `Fusion` forms report the candidate name `a+b`; the 300-member block form constructs;
the `context` block fetches no operator catalog and is refused with the misuse text before any spend.

## Outcome

Commits (after the second rebase): A ledger; B `refactor(sdk): port sf.Rank, sf.Concat and the selection
checks onto the reducer plan`; C `test(sdk): pin url4 goldens for every README and public-docs Fusion
example`; G `feat(sdk): lower the Fusion block form to sf.Fusion before compile`; fix `fix(sdk): report a
Rank or Concat url4 decode refusal as cannot rebuild, not as constructor text`; D `feat(sdk): rank members by
a named signal with sf.Rank(k, by_signal=..., order=...)`; E `feat(sdk): compile sf.Reduce('concat') as
sf.Concat`; F `feat(sdk): filter members by a signal threshold or a regex with sf.Filter`; H `test(sdk,engine):
run an SDK-written filter-then-model pipeline in the engine world`; I `docs(sdk): document sf.Rank by signal,
sf.Filter and the Fusion block form`; J this ledger.

### Grep outputs for Commit C (examples found)

`grep -n "Fusion(" packages/screamingface/README.md`: lines 57, 119, 134, 158, 222, 260, 261, 273, 290,
293, 303, 304, 339, 345, 387, 397, 418, 419, 422, 424, 428, 514, 528, 529 (24 examples).
`grep -rn "Fusion(" public-docs/src`: Index.vue:27, FirstFusionPage.vue:15, guides/PipelinesPage.vue:39 and
:45, guides/FusionsPage.vue:17, :24, :36, guides/EvaluationPage.vue:33, api/FusionsPage.vue:19,
QuickstartPage.vue:233 (10 examples). Non-examples (skipped): `fusionSig` (guides/FusionsPage.vue:39,
api/FusionsPage.vue:12), the `<td>` row (guides/FusionsPage.vue:163), and the repr outputs `basicOut` (:19),
`synthOut` (:32), `nestedOut` (:37), `recursiveOut` (guides/PipelinesPage.vue:43). 34 goldens plus 5 extra
recipes = 39 files in `ST/data/fusion_docs/` (+ the 300-member one is among the extras).
FR#2 guard list: `ST/data/*.url4` through `test_reducer_characterization.py`; the
`ET/data/combine_contract/*.url4` drift guards; `ST/test_url4.py`. None changed since Commit C.

### RED / GREEN

| Row | Test | RED | GREEN |
|---|---|---|---|
| B#1 | `test_rank_concat_plan.py` (2 tests) | assertion: `() == (judge signal call,)` and `'' == 'Rank'` (stubs) | B |
| B#2 | every replayed 10S test; `test_vote_and_judge_are_not_selections` (in place) | guards, pass at once after the port (post-rebase red set: whole package import) | B |
| C#3-4 | `test_fusion_doc_goldens.py` (40 rows) | none: CHAR, pass at once | C |
| G#17-18 | `test_block_form_rewrites_to_fusion_and_compiles_byte_identical` (17), characterized goldens (2), keeps-the-rest | code's own `ValueError` (operator catalog needed, member cap) | G |
| G#19-21 | recipe-synthesizer flag, named pipeline, nested (both block forms) | assertion / `ValueError` | G |
| G#22 | `test_reducer_synthesizer_fusion_is_unchanged` (20), identity rows | none: guards, 22 rows passed on the identity stub | G |
| G#23-26 | no operator fetch, 300 members, misuse (9 + 3 through a Client), op ids (17), `to_python`, candidate name | `ValueError`, `EngineCapabilityError`, regex mismatch, assertion | G |
| G#27 | `test_blocks_reduce.py` (in place) | passes at once | G |
| fix | 4 tamper rows (k zero, k above members, path, empty separator) | assertion: constructor text | fix commit |
| D#5-8 | `test_rank_by_signal.py` (19 tests), round trip and tamper rows (in place), recovery rows | code's own `ValueError` (old message, "not supported yet", "does not compile"), assertion | D |
| E#9 | `test_concat_block.py` (7) | `ValueError ... does not compile`, assertion | E |
| F#10-15 | `test_filter.py` (46 tests): comparisons, GE21 typed key, non-finite, plan, last stage, block equality, round trip, 17 tamper rows | 37 x `ValueError: 'filter' is not a known reducer`, assertion (typed key, `__bool__`, non-finite on the stub) | F |
| F#16 | in place: `ENGINE_OPERATOR_IDS`, rglob, `test_block_surface.py`, `not_yet` | rglob/ids: `unknown reduce operator 'filter'` | F |
| H#28 | `test_filter_contract_fixture.py` | assertion: fixture file missing | `write_fixture()` |
| H#29 | `ET/test_filter_contract.py` | none: CHAR, passes at once | H |

Amendments: (a) GE21 RED row for `_Comparison` (typed key, `True` vs `1`): F, assertion on the stub. (b) fix
commit and `_decoded` for Rank, Concat, Filter. (c) `test_the_same_order_goes_into_both_steps` (D, 12
params, block included). (d) accounting keys on Rank and Filter emit `sources` (D, F). (e) the `== True`
note is in the Filter docstring, README and CHANGELOG. (f) `test_a_filter_evidence_case_decodes_...` (F) and
the engine score assertion `[1.0, 0.0, 1.0, 0.0]` (H).

### Gates (base `e4a-pick-merge-sdk`)

- `screamingface` (append-only on, once): offenders are the stack files that rule 2 allows and the snapshot:
  `tests/_reducer_fixtures.py`, `tests/public_surface_snapshot.json`, `tests/test_block_surface.py`,
  `tests/test_blocks_reduce.py`, `tests/test_vote_median_contract_fixtures.py`.
- `screamingface --skip-append-only`: ALL GATES GREEN (ruff, format, pyright, pytest with coverage, notebooks,
  build, distribution). Coverage 97.04% (gate 95%); `_evaluation/fusion_recipe.py` 100% (statement and
  branch). The first run failed one existing test: the rewrite recursed forever on a hand-made cyclic
  Pipeline (`test_pipeline_compilation.py`); fixed in `fix(sdk): leave a cyclic recipe to the compiler in
  the Fusion recipe rewrite` (an active-id guard, with a test), then green.
- `screamingface-engine --skip-append-only`: ALL GATES GREEN.
- `repo`: ALL GATES GREEN.
- `ET/test_filter_contract.py`, `ET/test_sdk_flow_catalog_fixture.py`, `ET/test_argmax_contract.py`: passed.
- Goldens (`ST/data/*.url4`, `ST/data/fusion_docs/`, `ET/data/combine_contract/*.url4`) unchanged since
  Commit C (the one new file is `filter_pipeline_candidate.url4`). The snapshot diff shows only Rank,
  Concat and Filter.

### Review fix round (ACCEPT AFTER FIXES)

1. A duplicate Candidate name made by the Fusion recipe rewrite now says so and asks for `name=`
   (`compilation._check_rewritten_names`); README and CHANGELOG say a block form is named from the rewritten
   recipe (GE22). 2. `_finite` adds `0.0`, so `-0.0` and `0.0` compile to the same bytes (RED row first).
3. `ENGINE_OPERATOR_IDS = dict(FLOW_OPERATOR_IDS)`; `engine_operators()` now covers every built-in, and
   `test_blocks_reduce.py` was updated in place. 4. One `_inferred_name`, `_inferred_self_name` and `_kept_name`
   in `recipe.py`, used by Fusion, CorrectiveLoop, SelfCorrective and the rewrite (name goldens unchanged).
5. AIDEV-NOTE for `1 in [s]`. 6. This ledger records the `-> Any` return. 7. `blocks.py` owns `_MAX_K` and
   `_MAX_SEPARATOR_CHARS` (selection imports them) and `_check_path` uses `_field_path` (256 cap, op-table
   message; one 9S row in `test_pick_merge_blocks.py` changed in place). 8. A Filter that keeps no member
   abstains (the engine's `kept@1` raises `no_votes`); docstring, README and CHANGELOG corrected.
9. `run_candidate(..., on_request=...)` and `operation()` live in `_signal_world`; four engine tests use them.

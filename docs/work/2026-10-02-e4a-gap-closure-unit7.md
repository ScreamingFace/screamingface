---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 7 -- Signal-weighted votes and the combine context sources

## Intent

Fold the weighted-vote part of the E4a gap-closure into the SDK on top of unit 5's `_plan()`
reducers. `sf.Vote` takes constant weights again and also `sf.signal(key)` weights; `sf.Reduce
("weighted")` and `sf.Vote(weights=...)` compile to the same Candidate (BK#4). A reducer that reads
an accounting signal (cost_usd, latency_ms, tokens_in, tokens_out) adds the combine context's
`sources`, built by a two-pass compile that counts every model call over the whole expression
(SG#5, SG#6, SG#9). `canonical_params` is a bound copy of the Engine's (SG#20). A signal-weighted
vote replays identically from the cache (SR#10), and `sf.Median(weights=...)` raises `TypeError`
(SR#9).

The branch was rebased with `git rebase --onto e4a-samples 298c12c4f e4a-weighted-vote`. The old
tip `22f24b513` is the reference for the port; the old ledger
`docs/work/2026-10-01-e4a-weighted-vote.md` is unchanged.

## Planned changes

- S2.0 rebase (done): four commits replayed. Conflicts: `reducer.py` (stops 1 and 4: HEAD taken),
  `fusion.py` (taken from HEAD at every stop), the snapshot (HEAD), CHANGELOG (stop 1: parent text
  kept, unit 7 bullet inserted after the `sf.Vote`/`sf.Median` bullet). README merged cleanly.
  `git diff e4a-samples HEAD -- packages/screamingface/src` is empty after the rebase.
- Red set after the rebase (the replayed commits are red until Commit C; a rebase artifact):
  `tests/test_weighted_vote.py` fails at collection (`TypeError: Vote.__init__() got an unexpected
  keyword argument 'weights'`, module-level `_spec`); `tests/test_weighted_vote_contract_fixture.py`
  (same TypeError); engine `test_empty_extract_weight_does_not_count` (`'fail' != 'empty'`).
  Nothing else is red in the focused sets.
- B: pin the weighted-vote evidence in the Answer-row wire (engine test, in place).
- C: `reducer.py` `_weights_option`, `_MAX_WEIGHT`, `_vote_plan`; `Vote(weights=...)` and
  `Median(weights=None)` on `_plan()`; `_MAX_REDUCER_MEMBERS` moves into `reducer.py`; `blocks.py`
  calls the shared validator and plan.
- D: `sf.signal` weights on `Vote` and `Reduce("weighted")`; `_spec_weights`, `accounting_signal`.
- E: `Vote(weights=...)` against `Reduce("weighted")` guard.
- F: `_evaluation/combine_sources.py`, the two-pass `compile_candidate`, the conformance test, the
  workflow path filter.
- G: signal-vote replay (SDK and engine halves), drift guard fixture, SR-1 CHAR.
- H: CHANGELOG and README. I: this ledger closed.

## Test plan

Rows (spec S3): 1 SR#9 median rejects weights (C); 2 BK#8 weighted recovers as `sf.Vote`, in place
(C); 3 signal weights compile (D); 4 `score:judge` waits for the judge (D); 5 repr, python and
recovery (D); 6 `Vote` against `Reduce("weighted")` (E, guard); 7 SG#5 sources only for accounting
keys (F); 8 SG#9 claimants over the whole expression (F); 9 SG#20 dotted param key (F); 10
conformance guard (F, RED from the stub); 11 SG#6 goldens unchanged (F, guard); 12 drift guard
(G); 13 SR#10 SDK half (G); 14 SR#10 engine half (G, CHAR); 15 SR-1 CHAR (G).

Guard, CHAR and repair rows (no RED expected): B, 6, 11, 14, 15. Row 10 has a RED from its stub.

## Notes

Decisions F1-F15 come from the unit spec. What happened, per flag:

- F1 `reducer.py` and `fusion.py` were taken from HEAD at each stop that touched them (stops 1 and 4
  conflicted in `reducer.py`; stops 2 and 3 were clean); Commit C ported the logic onto `_plan()`.
  `git diff e4a-samples HEAD -- packages/screamingface/src` was empty after the rebase.
- Rebase stop 1 (`2463484c1`): conflicts in `reducer.py` (HEAD taken) and `CHANGELOG.md` (parent
  text kept, unit 7 bullet inserted after the `sf.Vote`/`sf.Median` bullet); `README.md` and the
  snapshot merged by git, and the snapshot was reset to HEAD. Stop 4 (`22f24b513`): `reducer.py`
  only (HEAD taken). CHANGELOG and README merged cleanly there.
- The parent `e4a-samples` moved from `288a66f10` to `7d9518ddd` (a test tidy of two files) while this
  unit was built. The branch was rebased onto it again with no conflict.
- F2 S1-S4 were fixed in Commits B, C and D as planned. The collection error of
  `ST/test_weighted_vote.py` (a module-level `_spec`) is the red set; it is one error, not one
  failure per test.
- F3 a member with ANY call claimed twice or more gets `{}`; the adapter turns `{}` into all None.
  Errata: erd s6 must say "any", not "every".
- F4 two-pass compile in `compile_candidate`; pass 2 shares `warned_fusions` (one
  `DuplicateMembersWarning`, pinned by the duplicate-members row).
- F5 claimants are every `_model` / `_model_synthesizer` emission; combine calls are not counted.
- F7 `canonical_params` is a copy; `STU/test_canonical_params_conformance.py` binds the `return`
  expression, the argument names and the `quote` import. Workflow path filter added (F15).
- F8 `score:judge` weights raise `ValueError` ("needs a judge") in `_vote_plan`, at compile.
  Errata: 8S removes this branch.
- F9 one `_weights_option` and one `_MAX_WEIGHT` in `reducer.py`. `blocks.py` needs no cap import
  any more, because its own `_check_weight` is gone. Unit 4's BK#7 rows pass unchanged.
- F10 pinned both ways in one test: `sf.Median(weights=...)` raises `TypeError` ("weights apply to
  Vote only") and `sf.Reduce("median", weights=...)` raises `ValueError` ("does not take option").
- F11 pinned by `test_a_corrective_round_claims_every_member_call_again`: with `max_rounds` of 2 the
  url4 holds `sources: {member_1: {}, member_2: {}}`. The substring needs no unescaping.
- F13 AIDEV-NOTE in `_reducer_synthesizer`. F14 not here.
- Spec differences, where the code won: the tally values of the vote with the `text` normalizer are
  lower case (`"a"`, `"b"`), so the SR#10 and SR-1 assertions use those; the output keeps its case.
  The tally row key for the holders is `holders`. `_attempt` and `_cost` are imported from
  `test_signal_accounting_connector.py` and not copied.
- Extra commit: `test(sdk): satisfy pyright ...` fixes three pyright errors in the new tests and
  adds one malformed-weights case (reducer.py line 231).
- Two in-place edits to unit 4 and unit 5 tests: `_named_or_block` and the S4 row in
  `test_blocks_reduce.py`, and the BK#8 weighted row in `test_reducer_recovery_preference.py`
  (plus one extra row: a weighted block with a regex rule stays `sf.Reduce`).

## Results

RED / GREEN per row (RED = an assertion, or the code's own error, before the GREEN code):

| Row | Commit | RED | Note |
|---|---|---|---|
| 1 SR#9 median rejects weights | C | assertion (regex vs Python's own TypeError) | |
| 2 BK#8 weighted recovers as Vote | C | assertion (type is Reduce) | in place |
| 3 signal weights compile | D | unit 4 "arrives with" ValueError | Reduce form first |
| 4 score:judge waits | D | assertion (regex mismatch) | |
| 5 repr, python, recovery | D | TypeError of `_weights_option` (and "cannot rebuild" rows) | |
| 6 Vote vs Reduce('weighted') | E | none | guard: one `_vote_plan` |
| 7 SG#5 sources | F | assertion (no sources key) | controls pass at once |
| 8 SG#9 claimants | F | assertion (no sources key) | |
| 9 SG#20 dotted key | F | assertion | |
| 10 conformance | F | assertion (stub AST and corpus) | after the stub |
| 11 SG#6 goldens | F | none | guard |
| 12 drift guard | G | assertion (fixture missing) | then `write_fixture()` |
| 13 SR#10 SDK half | G | none at once; RED shown by switching `_accounting_sources` off | |
| 14 SR#10 engine half | G | none | CHAR; signals were not None |
| 15 SR-1 CHAR | G | drift guard RED for the new key, then regenerated | engine test passes at once |
| B repair | B | none | repair |

Gates (from the worktree, after the second rebase):

- `run_gates.py screamingface --base e4a-samples` (once, no skip): FAILED on the append-only check, as
  planned. Offenders: `tests/public_surface_snapshot.json`, `tests/test_blocks_reduce.py`,
  `tests/test_reducer_recovery_preference.py`.
- `run_gates.py screamingface --base e4a-samples --skip-append-only`: ALL GATES GREEN.
- `run_gates.py screamingface-engine --base e4a-samples --skip-append-only`: ALL GATES GREEN.
- `run_gates.py repo`: ALL GATES GREEN.
- Coverage (SDK suite): total 97 %; `_evaluation/combine_sources.py` 100 %; `combine_spec.py` 100 %.
- Focused SDK + engine sets: 347 and 29 passed.

## Outcome

Done. Signal weights on `sf.Vote` and `sf.Reduce("weighted")`, the combine context `sources`, the
conformance bind and the replay tests are in. Not done here, by design: `score:judge` weights (8S),
`by_signal` reads (9S, 10S), the live latency note (unit 12).

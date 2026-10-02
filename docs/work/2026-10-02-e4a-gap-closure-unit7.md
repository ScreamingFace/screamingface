---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
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

Decisions F1-F15 come from the unit spec. Results and errata are recorded in Commit I.

## Outcome

Open.

---
ticket: OME-1463
stack: screamingface
status: done        # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# OME-1463 — send the archive cache saving; a fully priced cached run is complete

## Intent

Decision D7 on `OME-1251` (owner, 2026-10-02, reverses D3): the published run cost is the full
cost of the run, spend plus what its cache hits would have cost, counting archive-matched prices.
The board sums the parts (`OME-1382`, PR #1227). This unit is the SDK half: carry and send the
archive saving, and submit a cached run as `complete` when every hit carries a price, instead of
`OME-1441`'s "any hit means `partial`". It is what lets the seeded draco-3pass rows (`OME-1384`)
publish a real cost without a paid rerun. Spec: `docs/spec/2026-10-02-OME-1463-archive-cost.md`.

## Planned changes

- `packages/screamingface/src/screamingface/_engine/contract.py`: read the run summary's
  `cache.saved_cost.unpriced_hits`; carry it on `_RunOutcome` (None when no summary arrived).
- `packages/screamingface/src/screamingface/_core/ports.py`: `_RunOutcome.cache_unpriced_hits`.
- `packages/screamingface/src/screamingface/report.py`: public `CandidateResult.cache_saved_cost_archive_usd`
  and `CandidateResult.cache_unpriced_hits`, in `to_dict`.
- `packages/screamingface/src/screamingface/_evaluation/results.py`: pass both through; the local
  status rule stays as is.
- `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py`: `_published_cost` per D7;
  send `cache_saved_cost_archive_usd` when present.
- `packages/screamingface/tests/`: new tests; `test_cached_run_not_complete.py` cases whose rule D7
  changes (owner decision).
- `packages/screamingface/tests/public_surface_snapshot.json`, `CHANGELOG.md`.

## Test plan

- Decoder: summary `unpriced_hits` read and validated; absent summary leaves it None.
- Published pair: hits all priced (summary unpriced 0) and spend priced -> `complete` + spend +
  both savings; any unpriced hit -> `partial`, no amount; no summary but hits -> `partial`;
  spend unpriced + hits -> `partial`; no hits -> unchanged.
- Archive saving sent as a decimal string, omitted when absent, never added to the spend.

## Acceptance

- A fully archive-priced cached run submits `complete` with spend and the archive saving.
- A run with any unpriced hit, or without a run summary, never submits `complete`.
- `run_gates.py screamingface` green. Merges only after the board half is live on dev.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `_evaluation/results.py::_run_cost_status` (archive saving now
  counts as evidence for `partial`), the `report.py` status-validator call site (same evidence),
  and prior tests in `tests/test_cache_saved_cost_submission.py` and `tests/test_run_cost_status.py`.
  New: `tests/test_archive_cost.py` (20 tests). Docs: spec, plan, this ledger.
- **Commits:** see the PR (one `feat(screamingface)` commit).
- **Gates:** `run_gates.py screamingface --skip-append-only` all 7 green: ruff, format, pyright,
  pytest with coverage >= 95 (2210 passed, 26 skipped), notebooks, build, distribution. The
  append-only check was skipped for the approved prior-test rewrites and the snapshot.
- **Deviations:**
  - `test_cached_run_not_complete.py` needed NO change: its results never set
    `cache_unpriced_hits`, so it is unknown and every hit case still sends `partial` (spec D3).
  - Instead, five prior tests encoded D3 ("archive money is never published / never evidence")
    and were rewritten for D7 with owner approval (2026-10-02): `test_archive_money_never_reaches_
    the_result_or_the_board` (now `..._reaches_...`), `test_the_archive_rule_holds_when_the_clock_
    reads_zero_point_five` (archive appears exactly once, compared as numbers), the else-branch of
    `test_no_evaluated_run_pairs_unavailable_with_a_saving`, and in `test_run_cost_status.py`
    `..._only_archive_savings_derives_unavailable` (now `..._partial`) and the asymmetry test
    (now `test_either_saving_is_evidence_and_no_saving_stays_unavailable`). One new test added.
  - Real bug avoided: an archive-only unpriced run was `unavailable` locally; with the archive
    saving now sent, the board would refuse that pair (422, confirmed by the board half's
    author). It is `partial` now, on the result and the submission.
  - `report.py`, `contract.py`, `leaderboards.py` were already over 450 lines before this change;
    only a few lines were added, not split.

## Review round 1 (2026-10-03, taken over by the general-work session)

The draco3-rerun session that opened #1229 had ended; Filip asked general-work to take over.

- **P1, fixed: the proof and the money came from different evidence.** `_engine/contract.py` now
  parses the whole run summary into `_CacheSummary` and `_RunState._cache_evidence` takes both
  savings from it, publishing `unpriced_hits` only when the summary is consistent (counts sum to
  hits, a total exactly when its provenance had hits, final hit count equals the summary's). A
  summary amount must be a decimal string; anything else raises `ExecutionError` (fail closed).
- **P2, fixed: the public `Span` docstring** said the two savings must never be added. It now
  separates the raw provenance-specific measurements (never combined on an event) from the
  Scoreboard's reproduction-cost policy (adds them once a run's pricing coverage is complete).
- **Tests:** 13 new in `tests/test_archive_cost.py` (summary amounts beat missing or disagreeing
  span totals, archive total, four inconsistent-summary cases, an unaccounted hit span, four
  malformed amounts, and the reviewer's case end to end). RED first: 12 failed for the stated
  reason. One test from this PR's first commit,
  `test_the_summary_count_of_unpriced_hits_is_carried`, set `unpriced_hits = 2` on a 1-hit summary,
  which the fix now correctly rejects as inconsistent; its setup now states a consistent 3-hit
  summary, keeping its intent (the count is carried). It is new in this PR, not on `main`.
- **Mutations (all caught):** amounts taken from spans (4 tests); consistency check removed (5);
  final-hit-count check removed (1); float summary amount accepted (1).
- **Gates:** `run_gates.py screamingface --base origin/main --skip-append-only` ALL GATES GREEN.
  The skip covers only the owner-approved D3-to-D7 rewrites from this PR's first commit; this round
  changed no test outside `test_archive_cost.py`.

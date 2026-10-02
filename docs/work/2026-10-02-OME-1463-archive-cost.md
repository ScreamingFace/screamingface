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

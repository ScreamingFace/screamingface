# Plan: OME-1463 — send the archive cache saving; a fully priced cached run is complete

Spec: `docs/spec/2026-10-02-OME-1463-archive-cost.md` (approved 2026-10-02). Ledger:
`docs/work/2026-10-02-OME-1463-archive-cost.md`. Stack: `screamingface` (sdlc-python).

## Steps (TDD, one commit at the end)

1. **RED** `tests/test_archive_cost.py` (new):
   - decoder: the real `cache_hit_contract` fixture, with `cache.saved_cost.unpriced_hits` set on
     the root summary log, yields `_RunOutcome.cache_unpriced_hits`; summary without the key or no
     summary at all yields `None`; a negative / bool / non-int value raises `ExecutionError`.
   - `CandidateResult`: carries `cache_saved_cost_archive_usd` and `cache_unpriced_hits`, exports
     both in `to_dict`, validates them like the existing saving and hit count.
   - `_submission`: the five rows of the spec's published-pair table; the archive saving sent as a
     decimal string, omitted when absent, never added to `run_cost_usd`.
2. **GREEN**
   - `_core/ports.py`: `_RunOutcome.cache_unpriced_hits: int | None = None`.
   - `_engine/contract.py`: read `cache.saved_cost.unpriced_hits` from the root summary next to
     `cache.hits`; reuse `_cache_hit_count` for validation; carry it on the outcome.
   - `report.py`: the two fields, constructor kwargs (default `None`), validation, `to_dict`.
   - `_evaluation/results.py`: pass both through.
   - `_scoreboard/leaderboards.py`: `_published_cost` per the table; payload adds
     `cache_saved_cost_archive_usd`.
3. **Prior tests**: update the `test_cached_run_not_complete.py` cases that D7 flips (owner
   approval 2026-10-02). Everything else stays unmodified.
4. Public-surface snapshot regenerated; CHANGELOG Features entry.
5. Gates: `uv run .claude/scripts/run_gates.py screamingface` (append-only check skipped only for
   the approved prior-test and snapshot changes).
6. Commit, PR (draft until the board half of OME-1382 is live on dev).

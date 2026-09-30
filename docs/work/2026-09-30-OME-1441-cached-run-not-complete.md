---
ticket: OME-1441
stack: screamingface
status: done      # planned | in_progress | done | blocked
started: 2026-09-30
finished: 2026-09-30
---

# cached-run-not-complete — stop publishing a cached run's $0 spend as a complete cost

## Intent

A run served partly or wholly from the gateway cache spends little or nothing, and the SDK
publishes that spend as a `complete` cost. The board then ranks a fake ~$0 on the Pareto frontier
(`OME-1143`, and the 10 stored draco-3pass rows in `OME-1384`). Owner decision 2026-09-30: until the
board ranks on spend plus saving (`OME-1382`), a submission from a run with ANY cache hit is
published as `partial` with no amount. The local report keeps its true spend and status; only what
is submitted changes. Parent epic `OME-1251`. Spec `docs/spec/2026-09-30-cached-run-not-complete.md`.

## Planned changes

- `packages/screamingface/src/screamingface/_engine/contract.py`: count spans whose
  `cache_status == "hit"` per run; carry the count on `_RunOutcome`.
- `packages/screamingface/src/screamingface/_core/ports.py`: `_RunOutcome.cache_hits: int = 0`.
- `packages/screamingface/src/screamingface/report.py`: `CandidateResult.cache_hits` (public,
  read-only, in `to_dict`).
- `packages/screamingface/src/screamingface/_evaluation/results.py`: pass the count through.
- `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py`: `_submission` publishes
  `run_cost_status="partial"` and omits `run_cost_usd` when `cache_hits > 0`; the saving, when
  present, is still sent.

## Test plan

- Contract: a run whose spans include one `hit` reports `cache_hits == 1`; misses and bypasses
  count zero; no spans count zero.
- Submission: a result with `cache_hits > 0` and a priced spend submits `partial` and no
  `run_cost_usd`; with a saving present it still sends `cache_saved_cost_usd`.
- Submission: a result with `cache_hits == 0` is unchanged (`complete` plus amount), including a
  `no-store` run whose calls are all bypasses.
- The local `CandidateResult` keeps `usage.cost_usd` and `run_cost_status == "complete"` for a
  cached run: only the payload changes.
- The payload pair stays valid for the board: `partial` never carries an amount.

## Acceptance

- A submitted run with any cache hit never reaches the board as `complete`.
- An uncached run submits exactly as today.
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the five planned source files, plus `tests/test_cached_run_not_complete.py`
  (new, 16 tests), `tests/public_surface_snapshot.json` (`CandidateResult.cache_hits` field and
  `__init__` kwarg, owner-approved 2026-09-30), and `CHANGELOG.md` (Bug Fixes entry).
- **Commits:** see the PR (one `fix(screamingface)` commit).
- **Gates:** `run_gates.py screamingface --skip-append-only` all green: ruff check, ruff format,
  pyright (0 errors), pytest with coverage >= 95 (2099 passed, 26 skipped), notebook check,
  `uv build`, distribution check. The append-only check was skipped because its only hit was
  the public surface snapshot, whose update the owner approved.
- **Deviations:**
  - The count is `max(run summary cache.hits, hit spans)`, not only hit spans. A span keeps
    only its last call's cache outcome, so spans undercount. The Engine's run summary counts
    every round trip (spec D5 amendment).
  - An invalid summary count (negative, bool, non-int) raises `ExecutionError` instead of
    being ignored.
  - Review of #1187 (P2): the first version downgraded only `complete`, so an unpriced cached
    run still went out as `unavailable`, against D1 and the spec's payload table. Owner decision
    2026-09-30: follow the spec. Any hit now sends `partial`, whatever the local status, so the
    status sent depends on the hit count alone. `unavailable` is left for uncached runs whose
    spend could not be priced. The board accepts `partial` with neither an amount nor a saving
    (`scores/schemas.py` `validate_cost_matches_its_status`). Its comment still defines
    `partial` as "saving evidence exists"; that wording is updated under `OME-1442`.
  - Not solved here: older SDKs and non-SDK clients still submit cached runs as `complete`
    (board-side enforcement is a separate follow-up), and the stored rows need `OME-1384`.

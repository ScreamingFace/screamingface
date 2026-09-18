---
ticket: unfiled — PR #930 review round 3 (Linear filing skipped by owner, as in round 2)
stack: screamingface-engine, aigateway, url4
status: done
started: 2026-09-16
finished: 2026-09-16
---

# PR #930 review round 3 — close HupBaHa's four remaining findings

## Intent

HupBaHa's follow-up review on head `44be27d7` left four correctness findings open. Two are
honesty defects in published numbers (a cache hit that follows a transport retry claims a spend
of exactly zero it cannot prove; a saved-cost total silently rounds once enough contributions
accumulate). Two are in the snapshot loader (the exactness lock introduced in round 2 blocks
cache-hit serving for the whole merge, contradicting an approved availability contract; and the
`metadata_degraded` count misses the rows the stale-metadata trigger clears, so it can report
zero while degrading rows). All four publish a figure an operator would read as a fact.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner/connector.py` — F1: a retried hit
  publishes `cost_usd=None` ("not priced") instead of `Decimal(0)` ("was free").
- `apps/screamingface-engine/src/screamingface_engine/runner/cache_counters.py` — F3: derive the
  addition precision from the operands' exponent span; `AMOUNT_PRECISION` becomes a floor.
- `apps/aigateway/src/aigateway/core/request_cache/bulk_loader.py` — F2: drop the
  `SHARE ROW EXCLUSIVE` table lock and its `lock_timeout`, restoring "the load never blocks
  serving"; F4: extend `_DEGRADED_COUNT_SQL` to mirror the trigger's `WHEN` clause.
- `apps/aigateway/src/aigateway/core/admin_schemas.py` — F2/F4: `metadata_degraded` is documented
  as a LOWER BOUND.
- `apps/aigateway/DEPLOYMENT.md`, `docs/spec/2026-09-13-cache-entry-metadata-erd.md` — retract the
  round-2 maintenance-window guidance the lock made necessary.
- Tests: new files for F1/F3; extend the Postgres integration file for F2/F4.

## Test plan

- F1: a hit after a retry reports `cost_usd is None`; an unretried hit still reports `Decimal(0)`;
  the run total latches `unpriced` rather than summing a false zero; tokens stay zero either way.
- F3: the reviewer's own repro — 1000 × `999999999999999999.000000000000000000000000000000001`
  must equal the exact sum, checked against a `Fraction` ground truth so no Decimal context can
  launder the comparison. Plus: precision never shrinks below `AMOUNT_PRECISION`; a non-finite
  input cannot crash the accumulator.
- F2: a racing write to an unrelated row no longer blocks the merge (the inverse of the round-2
  test); a cache hit served during a merge does not stall.
- F4: a staged row whose metadata equals the live block but whose response differs is COUNTED as
  degraded, and is in fact degraded by the trigger.

## Acceptance

- All four findings closed with a test that fails without the change.
- `run_gates.py` green on `screamingface-engine`, `aigateway`, `url4`.
- No published figure claims more certainty than its evidence supports.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus three not foreseen —
  `apps/aigateway/src/aigateway/core/request_cache/upload_job.py` (the `merge_lock_timeout`
  refusal became unreachable once the lock went, so it left `REFUSAL_CODES` with it),
  `apps/aigateway/tests/unit/test_cache_upload_job_runner.py` (its test for that refusal was
  removed), and `apps/aigateway/tests/integration/test_cache_snapshot_entry_metadata_postgres.py`
  (the round-2 racing test was revised — see Deviations).
- **Commits:** see the branch tip — `fix(cache): close PR #930 review round 3`.
- **Gates:** `screamingface-engine` ALL GREEN · `aigateway` ALL GREEN (`--skip-append-only`,
  see Deviations) · `url4` ALL GREEN. Postgres integration: 37 passed, 5 failed — all five are
  `FileNotFoundError: 'pg_dump'`, a missing local binary, verified identical on a stashed tree
  before any change; CI provides `pg_dump`.
- **Deviations:**
  - **Finding 2 — design chosen by the owner.** Two designs were put up: (A) drop the table lock
    and name `metadata_degraded` an explicit lower bound, and (B) replace it with row-level
    `SELECT … FOR UPDATE` over the colliding join. The owner chose **A**. B was rejected on the
    reasoning that it still cannot lock a row that does not yet exist, so the published wording
    would stay "at least" either way — it buys accuracy under concurrency, not exactness, at the
    cost of row locks across the whole colliding set. That reasoning is recorded in the ERD and
    in `_DEGRADED_COUNT_SQL` so it is not re-litigated silently.
  - **Append-only gate overridden on `aigateway` (SDLC rule 5), with prior owner approval.** The
    Confidence Gate was raised BEFORE any code was written: the owner was told
    `test_a_racing_write_to_an_unrelated_row_blocks_the_merge` asserts the table lock *as the
    fix*, so choosing A necessarily inverts it, and answered "go with A, fix all four". Two prior
    tests changed:
    - `test_a_racing_write_to_an_unrelated_row_blocks_the_merge` → REVISED and renamed to
      `..._no_longer_blocks_the_merge`. Kept rather than deleted: its docstring now records the
      reversal and why, so the round-2 reasoning survives as history instead of vanishing.
    - `test_a_merge_lock_timeout_maps_to_its_code_and_is_legible` → DELETED. It covered the
      `merge_lock_timeout` refusal, which round 2 added and round 3 removes; a test for an
      unreachable path is not evidence. Its absence is now pinned positively by
      `test_the_merge_no_longer_offers_a_lock_timeout_refusal`, so the refusal cannot return
      unnoticed. Both `merge_lock_timeout` and `MergeLockTimedOut` were introduced on THIS branch
      and never shipped, so removing them breaks no released API surface (verified against
      `origin/main`).
  - **Finding 1 scoped to the hit path.** The reviewer's wording ("call and run cost accounting")
    could be read to cover a retried MISS too, whose reported cost is also only a lower bound
    (attempt 1's `_aigw` dies with its lost reply). Not broadened: that would cost every run its
    entire cost total on a single transport blip, which is a values decision well under the 95%
    bar. Recorded as an AIDEV-NOTE at the seam rather than acted on.
  - **Adjacent defect found, deliberately NOT fixed.** `executor._fold_usage` accumulates
    `self._subtree_cost += event.cost_usd` under the AMBIENT 28-digit context — the same class of
    bug as finding 3, on the spend total rather than the saved-cost total. It predates this PR and
    the reviewer did not raise it. Flagged to the owner instead of being fixed silently, so the
    scope of this round stays what was agreed.
  - **Linear filing skipped** at the owner's instruction, as in round 2. Process debt, noted here
    so it is visible rather than lost.

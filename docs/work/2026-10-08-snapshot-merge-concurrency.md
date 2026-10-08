---
ticket: OME-1221   # existing bug issue; no new issue is filed
stack: aigateway
status: in_progress
started: 2026-10-08
finished:
---

# snapshot-merge-concurrency — a same-key hit never waits for a snapshot merge; the degradation count stops over-attributing

## Intent

OME-1221 (follow-up of the PR #930 review). Two concurrency gaps in the admin cache snapshot
merge (OME-951):

1. A cache hit awaits its `hit_count`/`last_hit_at` bump before returning the body. On a key the
   archive also carries, that `UPDATE` queues behind the merge's row lock until the merge commits,
   so the hit stalls despite spec §7 "the load never blocks serving".
2. `metadata_degraded` is counted before the merge with no lock. It undercounts a racing fill
   and over-attributes a degradation a concurrent writer caused, so "at least" is not true.

Owner decision (2026-10-08, option A2): a hit never waits for a merge, and concurrent hits still
all count (plan §8.13). The merge holds a transaction advisory lock. The bump first takes the row
only if it is free (`FOR UPDATE SKIP LOCKED`); if the row is taken, it waits only when
`pg_try_advisory_xact_lock_shared` shows no merge is running. Otherwise the hit is served
uncounted. §7 holds as written, so no contract change. The count locks the colliding rows it counts
(`FOR UPDATE`) in the merge's transaction. It is then exact for every row that existed at count
time and errs only downward (a fill inserted after the lock), so "at least" becomes true.

## Planned changes

- `apps/aigateway/src/aigateway/core/request_cache/store.py`: on Postgres, `record_hit_metadata`
  bumps through a `FOR UPDATE SKIP LOCKED` subselect, then (row taken) a merge-aware update;
  SQLite keeps the plain update. `MERGE_ADVISORY_LOCK_KEY` lives here.
- `apps/aigateway/src/aigateway/core/request_cache/bulk_loader.py`: `_DEGRADED_COUNT_SQL` locks
  the colliding live rows; the merge takes `MERGE_ADVISORY_LOCK_KEY` first; comments rewritten.
- `apps/aigateway/tests/integration/test_cache_snapshot_merge_same_key_postgres.py` (new).

## Test plan

- RED (PG): a hit on a key the open merge has locked returns the old body within a short timeout.
- RED (PG): a writer's uncommitted `response_json` change on a colliding row commits while the
  load waits; the trigger clears the block; the load reports 0 (today 1).
- Characterization (PG): a fill inserted during the load and then overwritten is uncounted; the
  error is downward only.
- PG: an uncontended hit still increments `hit_count`. Unit (SQLite): unchanged bump.

## Acceptance

- No hit waits on a merge's row lock (§7 holds for colliding keys).
- `metadata_degraded` never counts a row the load did not degrade.
- Gates green; PG lane green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `core/request_cache/store.py`, `core/request_cache/bulk_loader.py`,
  new `tests/integration/test_cache_snapshot_merge_same_key_postgres.py` (4 PG tests).
- **Commits:** one commit on branch `OME-1221-snapshot-merge-concurrency` — `fix(aigateway): never make a cache hit wait for a snapshot merge`.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` — ALL GATES GREEN
  (append-only, ruff check, ruff format, pyright, no-enterprise, pytest with coverage ≥ 80%);
  5339 passed, 101 skipped. PG lane `AIGW_TEST_PG=1 pytest tests/integration` with pg_dump 16:
  75 passed (with the host's pg_dump 15 the 5 known `pg_dump` round-trip tests fail on the
  client/server version mismatch, unrelated).
- **RED:** the colliding-key hit timed out waiting for the merge; the writer race reported
  `metadata_degraded = 1` for a block the writer cleared. The uncontended-hit and fill-race tests
  passed on main (characterization).
- **Mutation checks:** no merge advisory lock → the colliding-key hit test fails; count without
  `FOR UPDATE` → the writer-race test fails; no merge-aware second statement (pure `SKIP LOCKED`,
  the first option A) → the prior `test_every_concurrent_hit_is_counted` fails (10 of 20 counted).
- **Deviations:**
  - Option A (pure `SKIP LOCKED`) broke the prior plan §8.13 test, so the owner chose A2 instead;
    no prior test was changed.
  - No interleaving hook in production code: the tests drive every race with locks they hold (a
    test-only trigger parks the merge on an advisory lock; a writer's open transaction parks the
    load).
  - Not changed: `replace` still runs `TRUNCATE` (ACCESS EXCLUSIVE) and blocks reads for its
    transaction — a separate, known OME-951 finding, out of this ticket's scope. A fill that
    inserts a staged key after the count is still uncounted (the documented downward error).

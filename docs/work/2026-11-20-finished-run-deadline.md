---
ticket: OME-1992
stack: screamingface-engine
status: done
started: 2026-11-20
finished: 2026-11-20
---

# finished-run-deadline — leave a finished Run's deadline where it is

## Intent

When the follower of an attached Run that has already finished leaves, the Engine still moved the
Run's `deadline_at` forward by the orphan grace. Nothing acts on it, but `sf.runs` shows
`Run.deadline_at`, so a Run that was done showed a deadline in the future. Found in a local
end-to-end check of #1759; it was item 4 of OME-1967 until it moved to its own issue to land with
OME-1988's PR (#1977).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runs/store_driver.py`: `hold()` leaves a Run
  with no live Candidate alone.
- `apps/screamingface-engine/tests/unit/test_run_registry_driving.py`: one new test.

## Test plan

- `test_a_hold_leaves_a_finished_run_alone`: a Run whose only Candidate succeeded keeps its
  deadline after a hold 100 s later. Written first; it failed on the old `hold()`.

## Acceptance

- The new test passes, and every existing `hold()` test still does (an attached Run with live
  Candidates is still held forward; a detached, stopped or startless Run is still left alone).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger.
- **Commits:** one, on #1977's branch.
- **Gates:** the new test failed first (`[sqlite]`; Postgres skipped locally), then passed;
  `test_run_registry_driving.py`, `test_run_driver_ticks.py` and `test_run_owner_email_sealed.py`
  (every caller of `hold()`): 87 passed, 74 skipped (Postgres). ruff, ruff format and pyright clean
  on both files. CI runs the full gates.
- **Deviations:** none left (review round 2): `hold()` first checked for a live Candidate and
  then updated in two unlocked statements; it now does both in one transaction under the Run's
  lock, as `stop()` does. No `docs/tasks/` mirror, as for OME-1988 (owner).

## Review round 2 — 2026-11-20

From the second `/code-review` of #1977 (owner approved 2026-11-20; one commit with OME-1988's
round 2, `2026-11-20-fail-closed-record.md`).

- **Finding 2.** `hold()`'s live-Candidate check and its UPDATE were two unlocked statements,
  against the module's compare-and-set rule that `stop()` keeps with `lock_run`. Fix:
  `runs/store_driver.py::hold` runs both in one `in_transaction(CONNECTION)` after
  `lock_run(run_id, conn)`. A settle takes the same lock, so no Candidate ends between the check
  and the update.
- **Finding 6.** `runs/registry.py`, the `hold` port's docstring: a finished Run (no live
  Candidate) is left alone too.
- **Gates.** `test_a_hold_leaves_a_finished_run_alone` and every existing hold test pass
  unchanged: `test_run_registry_driving.py`, `test_run_driver_ticks.py` and
  `test_run_owner_email_sealed.py` 87 passed, 74 skipped on SQLite, and their Postgres parameters
  74 passed (testcontainers). No new test: the race needs two writers interleaved inside one
  call. ruff, ruff format and pyright clean on both files.

## Review round 3 — 2026-11-20

HupBaHa's review of #1977 (changes requested 2026-11-20 14:49, on 1b918257c), finding 2; the
owner approved the direction on 2026-11-20. One commit with OME-1988's round 3
(`2026-11-20-fail-closed-record.md`).

- **Finding 2.** `hold()` serializes with `settle()` through the Run's lock, but the periodic
  `reconcile()` bulk-updates stale Candidates to `lost` without it. On Postgres, reconcile could
  finish the last Candidate between hold's live check and its deadline update, so a finished Run
  got a moved deadline. Planned: after `lock_run`, `hold()` locks the Run's live Candidate rows
  (`select_for_update()`), so reconcile's UPDATE of them waits until hold commits; the check is
  the locked read. `reconcile()` is left as it is (one statement, no Run lock).
- **Test plan.** RED first: a Postgres race test with a barrier. hold is paused just before its
  deadline UPDATE (after its lock and live check); reconcile is started on another connection to
  settle the last Candidate `lost`; the test waits until reconcile has either finished or is
  waiting on a row lock (`pg_locks`), then asserts it is waiting, releases hold, and checks the
  end state. On the old `hold()` reconcile finishes inside the hold. SQLite cannot express the
  race (one connection, serialized by Tortoise), so the test is Postgres only.

### Review round 3 — outcome

- **Finding 2.** `runs/store_driver.py::hold`: after `lock_run`, the live check is
  `SELECT "id" FROM run_candidates WHERE run_id=… AND state IN (live) LIMIT 1 FOR UPDATE`
  (`select_for_update().only("id").first()`). The locked Candidate stays live until the hold
  commits, so reconcile's UPDATE of it waits, and the Run cannot finish between the check and
  the deadline update. Narrower than planned (one live row, not all): one is enough, and a hold
  that waits on no second row never closes a lock cycle with reconcile's many-row UPDATE (locking
  all of them could, when the two scan the rows in different orders, and Postgres would abort one).
  `reconcile()` unchanged.
- **Test.** `test_run_registry_writes_concurrency.py`, new
  `test_reconcile_never_finishes_the_last_candidate_inside_a_hold` (Postgres only). The barrier:
  `TransactionWrapper.execute_query` is patched to stop the hold's `UPDATE "runs" … "deadline_at"`
  until released, so the hold is paused after its lock and live check. Reconcile is then started
  on another pool connection to settle the Run's only Candidate `lost` (`lost_after` passed). The
  test polls until reconcile has finished or some statement waits for a lock (`pg_locks`, from a
  third connection), then reads the Run, releases the hold, and asserts: reconcile had not
  finished, the Candidate was still `scheduled` inside the hold, reconcile then settled it `lost`
  (1), and the deadline is the hold's (it landed while the Candidate was live). SQLite runs a
  transaction's statements on its one connection, held to the end, so it cannot express the race.
- **Gates.** RED on 1b918257c: the race test failed, reconcile finished inside the hold. GREEN:
  it passed 7 runs in a row on the final code; the run registry, store, driver, sweeps and runs files with
  Postgres on: 728 passed; the wider targeted set as in OME-1988's outcome. ruff, ruff format and
  pyright clean.
- **Deviations.** One live Candidate locked, not every one (above).

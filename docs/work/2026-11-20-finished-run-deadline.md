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

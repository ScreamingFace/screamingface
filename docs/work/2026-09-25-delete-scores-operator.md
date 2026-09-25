---
ticket: OME-1385
stack: scoreboard
status: in_progress
started: 2026-09-25
finished:
---

# delete-scores-operator — an operator module that deletes named scores from a public board

## Intent

`OME-1384`: the dev board's `draco-3pass` holds 7 scores from 2026-09-08 that publish a cached
run's spend, `0.000000`, as a priced cost. The owner decided (2026-09-25) to delete them and rerun
uncached. A rerun alone cannot replace them: identity is the recipe plus its score, so a faithful
rerun dedups to the old row (`scores/store.py:998`), and a replay never refills an amount that is
present. There is no delete route and no SQL access. Firecall does allow
`kubectl exec deploy/scoreboard -- python -m scoreboard.<module>`, which is how `OME-986` removed
three benchmarks. This unit adds that module for scores.

## Planned changes

- `apps/scoreboard/src/scoreboard/delete_scores.py`: new operator module
- `apps/scoreboard/tests/unit/test_delete_scores.py`: decision tests on the `tortoise_db` fixture
- `apps/scoreboard/tests/unit/test_delete_scores_cli.py`: `main()` against a real SQLite file,
  following `test_retire_benchmark_cli.py`
- `apps/scoreboard/DEPLOYMENT.md`: how to run it through `kubectl exec`

No schema change, no migration.

## Test plan

- dry run by default: nothing deleted, the matching rows reported
- `--yes` deletes exactly the selected rows; rows outside the selection survive, including the
  same benchmark's newer rows and other benchmarks' rows
- `--expect` mismatch refuses and deletes nothing, in both modes
- selection by exact ids, and by `--submitted-before`; ids from another benchmark are not matched
- unknown benchmark raises `LookupError`
- a private benchmark is refused, pointing at `purge_private_benchmark`
- the backup is the `export_private_submissions` JSONL of exactly the selected rows, on stdout
- idempotency keys of deleted rows go with them (cascade), others stay
- a delete count that differs from the selection rolls back (atomic)
- CLI: exit code, stdout carries only the backup, summary on stderr, connection closed

## Acceptance

- every test-plan bullet
- full `scoreboard` gates green
- `DEPLOYMENT.md` documents the dry run, the backup redirect and `--yes`

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `src/scoreboard/delete_scores.py`, `tests/unit/test_delete_scores.py`
  (15 tests), `tests/unit/test_delete_scores_cli.py` (11 tests), `DEPLOYMENT.md`. No schema change.
- **Commits:** see the PR.
- **Gates:** `run_gates.py scoreboard --base origin/main` ALL GREEN, without `--skip-append-only`.
  769 passed, 3 skipped. `delete_scores.py` at 99% coverage.
- **RED:** both files failed on `ModuleNotFoundError: scoreboard.delete_scores`.
- **Mutation check:** removing the count check (3 fail), the private refusal (1), the dry-run guard
  (2) and the short-delete rollback (1) each failed tests. Restored.
- **Deviations:**
  1. **`QuerySet.delete()`'s count is not a score count.** On SQLite it returned 4 for 2 scores,
     because it includes the idempotency keys removed by `ON DELETE CASCADE`. The short-delete
     guard caught it on the first GREEN run. The module now counts how many of the selected
     scores are gone, which means the same on every backend.
  2. **The visibility check moved inside the transaction.** The first version read `visibility`
     before opening it. `guards/test_visibility_exit_guard.py` flagged every exit: a board flipped
     private in between would have lost rows without `purge_private_benchmark`'s export proof. It
     is now `_revalidate_visibility_for_delete`, the first statement in the transaction, reusing
     `ScoreStore.visibility_query(lock=True)`. One test pins that it is called locked, on the
     transaction's connection.
  3. **Filed before PR-open,** at the owner's request (2026-09-25).

## Review round 1 (2026-09-26, owner's review)

**Finding (High), verified:** the confirmed run deleted and committed, and only then wrote the
backup to stdout (`main()` awaited `_run()` first). A dropped `kubectl exec`, a full disk or a failed
write in that window lost the rows and the backup together. The runbook compounded it: both runs
redirected to `backup.jsonl`, so the shell truncated the reviewed dry-run file as the confirmed
command started. My test checked the backup's content, never that it existed before the delete.

**Fix, as the review recommended, mirroring `purge_private_benchmark`:**

- the dry run prints the backup to stdout and its SHA-256 to stderr
- `--yes` requires `--expect-sha256`; the command recomputes the selected rows' JSONL digest inside
  the deleting transaction and refuses on mismatch, so a changed row is caught even when the count
  still matches
- the confirmed run writes nothing to stdout
- the runbook keeps the backup under its own name and checks it with `shasum -a 256`

**Tests:** 8 added (digest reported, digest required, malformed digest, changed selection refused,
case-insensitive digest, and three CLI paths). The tests in this PR's own new files were updated
for the new `--yes` contract; they are not prior-cycle tests. Mutation: disabling the digest
comparison fails 2 tests. Gates: ALL GREEN vs `origin/main`, no append-only exception.

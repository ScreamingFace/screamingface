# Delete named scores — plan

Spec: `docs/spec/2026-09-25-delete-scores-operator.md`.
Ledger: `docs/work/2026-09-25-delete-scores-operator.md`.
Branch `delete-scores-operator` from `origin/main` at `69971220`; renamed to `OME-N-…` at PR-open.

## Step 1 — RED

`tests/unit/test_delete_scores.py` (decision, `tortoise_db`) and `tests/unit/test_delete_scores_cli.py`
(real SQLite file, `main()`), covering every ledger test-plan bullet. Run; confirm each fails
because the module does not exist.

## Step 2 — GREEN

`src/scoreboard/delete_scores.py`, shaped like `retire_benchmark.py`:

- `DeletionRefused(RuntimeError)`
- `async def delete_scores(benchmark_id, *, score_ids=None, submitted_before=None, expected,
  confirmed=False) -> Deletion` — one decision function, no connection lifecycle
- `Deletion`: the selected `ScoreSchema` rows plus whether they were deleted, and a `describe()`
  line for stderr
- inside one `in_transaction()`: select, compare to `expected`, delete by `id__in`, compare the
  returned count
- `_run()` owns `init_db`/`close_db`; `main()` writes the backup bytes to stdout and the line to
  stderr, exits non-zero on a refusal

## Step 3 — DOCS

`DEPLOYMENT.md`: a "Deleting scores" section beside `retire_benchmark`: dry run with the redirect,
check the count and the backup, then `--yes`.

## Step 4 — GATES

`uv run .claude/scripts/run_gates.py scoreboard --base origin/main`. No prior test is touched, so
no append-only exception is expected.

## Step 5 — MUTATION CHECK, COMMIT, PR

Remove the `expected` comparison and confirm a test fails; drop the private refusal and confirm a
test fails. File the ticket, rename the branch, open the PR.

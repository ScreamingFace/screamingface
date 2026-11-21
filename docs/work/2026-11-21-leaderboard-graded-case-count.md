---
ticket: OME-1999
stack: scoreboard
status: done
started: 2026-11-21
finished: 2026-11-21
---

# leaderboard-graded-case-count — show on the leaderboard how many Cases each run graded

## Intent

A Benchmark run selects N Cases, and a Case can fail to be graded (the Candidate call errors or
times out, or the judge gives no readable verdict). The SDK already tells the submitter
("505 / 525 graded", the "Partial submission" notice), but none of that reaches the leaderboard:
the submission sends only the selected-Case total, failed Cases included, so a run that failed on
its hard Cases ranks like a complete one and a reader sees no sign of it. On Benchmarks whose
failure policy drops failed Cases from the score, that run even scores higher. An external
researcher asked for failures to be shown next to the score. This unit carries the graded-Case
count from the run to the leaderboard and shows it beside the score whenever it is below the total.

Out of scope, on purpose: ranking rules, scores, revisions and the Engine do not change.

## Design choices

- **One optional field, `graded_questions`**, named beside its neighbours `total_questions` and
  `correct_questions`. Failed Cases = `total_questions - graded_questions`; no second field.
- **The SDK sends it only for a run with at least one ungraded Case**, the "omitted when absent"
  rule `paper_url` and `cache_saved_cost_usd` already follow. Two reasons. The submission schema
  forbids unknown fields, so a scoreboard that predates the field answers 422 only to partial runs
  rather than to every submission. And the exhaustive payload-key guard
  (`test_the_submission_payload_gains_only_the_cost_key`) keeps passing unedited.
- **The count is the result's own gradeable count** (the figure its `coverage` is validated
  against), not a second formula. `coverage` itself cannot be used: it is rounded to 4 places, so
  on a large Benchmark a few failed Cases round to exactly 1.0.
- **Null means unknown, never "0 failed".** The column is nullable and not backfilled; every read
  schema leaves the key out when the row has no count, so old rows, old SDKs and the private
  export's bytes are unchanged.
- **Not part of recipe identity and not filled by a resubmission**, like `correct_questions`: the
  count is stored by the first submission of a row only.
- **Portal:** a quiet second line under the score on the Benchmark's leaderboard page
  ("505 / 525 graded", hover "20 of 525 Cases failed and were not graded"), the same second-line
  pattern the Backends cell uses for open/closed, in the existing small-label treatment. No new
  column, no new colour.
- **On the ranked leaderboard row only.** The field sits on `LeaderboardStoreEntry` (the row the
  ranking query builds) and its route mirror, not on `LeaderboardEntry` or `SpecHistoryRow`. Those
  two are pinned by prior tests that an added field breaks (an exact field set for the history
  row; a fixture that must give every optional entry field a value; a hand-built entry in the
  Pareto tests), and editing a prior test needs owner approval. So the submission-history page
  and a participant's own rows on a private Benchmark do not show the count yet.
- **No spec/plan artifact:** the owner approved the design at dispatch; it lives on the ticket.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/schemas.py` — field + validation on the submission;
  the field on the stored-score schema and the ranked row.
- `apps/scoreboard/src/scoreboard/scores/models/score.py`,
  `apps/scoreboard/src/scoreboard/scores/migrations/0026_score_graded_questions.py` — nullable column.
- `apps/scoreboard/src/scoreboard/scores/store.py` — write it, project it, select it in the ranking query.
- `apps/scoreboard/src/scoreboard/routes/leaderboard.py` — the ranked entry.
- `apps/scoreboard/portal/leaderboard-logic.js`, `benchmark.js`, `portal.css` — the note.
- `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` — send the count.

## Test plan

- Scoreboard `tests/unit/scores/test_graded_questions.py`: accepted in range; refused when
  negative, above the total, or not a whole number; stored and on the receipt; export carries it
  when present and omits it when absent; the leaderboard serves it when present and omits the key
  otherwise; a partly graded full run still ranks; the submit route answers 201 / 422.
- Scoreboard `tests/unit/test_migration_0026_score_graded_questions.py`: an existing row reads NULL.
- Portal `tests/portal/graded-note.test.js`: the wording, and the rendered Score cell.
- SDK `tests/test_graded_questions_submission.py`: a partial run sends the count; a complete run
  sends no key; the count reproduces the result's coverage; it reaches the wire, sync and async.

## Acceptance

- A submission from a run with ungraded Cases shows "G / N graded" beside its score.
- A row with no count (old SDK, old row, complete run) renders exactly as before.
- An out-of-range count is refused with 422.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `packages/screamingface/CHANGELOG.md`, and the new portal
  test file named in the scoreboard gate line (`.claude/sdlc.local.md`) and in
  `.github/workflows/scoreboard-tests.yml`, as both ask for new portal test files.
- **Commits:** `f94591ee8` — feat(scoreboard): show how many Cases each leaderboard entry graded;
  then the ledger and mirror commit.
- **Gates:** named test files only, per the owner's relevant-tests rule (the pre-push hook runs
  the scoreboard gates). Scoreboard: 606 passed, 28 skipped across the 23 test files that cover
  the touched code. Portal: 109 passed in 7 files. SDK: 197 passed in 6 files. ruff and pyright
  clean on every touched Python file.
- **Deviations:**
  - The history page and private-Benchmark own rows are left out (see Design choices): doing
    them needs three owner-approved prior-test edits.
  - The SDK sends the count only for a partly graded run, not always, so the exhaustive
    payload-key guard stays unedited.
  - A run with no graded Case cannot be submitted at all (it has no score), so the SDK never
    sends 0; the scoreboard still accepts 0 from other clients.
- **Owner-verify:**
  - Deploy the scoreboard (migration `0026`) BEFORE releasing the SDK: an older scoreboard
    answers 422 to a partly graded run from the new SDK.
  - Open PR #1981 also adds a migration numbered `0026` on top of `0025`; whichever merges second
    must renumber to `0027` and depend on the other.
  - Checked on a throwaway local scoreboard (SQLite, migrated to `0026`): the line renders in the
    light and dark themes with no horizontal scroll. Not checked on dev or prod.

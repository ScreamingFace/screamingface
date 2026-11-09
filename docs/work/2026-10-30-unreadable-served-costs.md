---
ticket: OME-1517
stack: scoreboard
status: done
started: 2026-10-30
finished: 2026-11-05
---

# Keep submission reads available with unreadable costs

## Intent

Serve unknown cost for a malformed/non-finite stored money value in history and
my_submissions, preserving rows and private export/receipt behavior. Authorized
with OME-969 and OME-430 on 2026-10-30.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/store.py`: narrow raw projections for the
  two served reads and reuse existing raw-column decoding/cost degradation.
- New HTTP regressions for each money field on both read surfaces, absent savings,
  valid sums, owner scoping, and unchanged private export bytes.
- PostgreSQL probe/tests for NUMERIC non-finite values; CI registration if needed.
- Spec, plan and task mirror.

## Test plan

Seed valid scores, then corrupt one of the three stored money columns with raw SQL.
Reproduce errors on SQLite for malformed text/NaN; verify HTTP 200 and null costs
without dropping good rows. Check PostgreSQL's accepted/rejected values. Validate
ordinary costs, history ordering/limit/owner filters and unchanged export content.
Run scoreboard gates and relevant PostgreSQL regressions.

## Acceptance

Both served reads keep the affected entry but publish no cost. Missing savings
still mean no additional cost. Stored columns, receipts and export bytes remain
unchanged; no migration.

## Outcome

Implementation merged; see closure below.

- Both served reads now use narrow raw projections, the existing money decoder,
  and the existing unreadable-saving policy. History retains valid stored parts.
  Non-money fields keep ORM conversion, including naive SQLite timestamps as UTC.
- RED: 18 HTTP failures across SQLite/PostgreSQL; 26 valid/rejection controls pass.
  PostgreSQL accepts NaN in NUMERIC but rejects malformed text. An added legacy
  timestamp regression caught naive timestamps losing UTC during raw projection.
- GREEN: all 46 new cross-backend cases pass; full PostgreSQL CI selection: 55
  passed. Local PostgreSQL 15; CI uses PostgreSQL 17.
- All scoreboard gates green: append-only, lint, formatting, types, full pytest
  with coverage floor and portal Node tests. Mirror status and whitespace checks pass.
- Export regression proves exact bytes and stored cost parts survive served reads.
  Existing receipt/export/deletion tests also remain green and unchanged.
- Commit: `fix(scoreboard): serve unknown costs for unreadable stored amounts`.
- No schema/model changes, migrations, dependencies or authentication changes.

## Wisdom review

Reuse the established raw decoder instead of adding a competing definition of
valid stored money. Apply owner/spec filters and history limits in SQL, and retain
history's narrow projection. The untouched _score_to_schema and all-list path
continue to serve exports and receipts. Unknown savings never become zero-cost
savings; only display responses degrade. Stored values are never rewritten.

## Deviations

The ticket described history as a whole-model read; main now uses a narrow model
projection. Kept that narrow field set when moving to raw decoding. PostgreSQL NaN
is affected too, so this is not exclusively a SQLite issue.

## Review follow-up — 2 November 2026

Replace driver-message regex matching with the structured PostgreSQL exception and SQLSTATE. Add explicit public-history corrupt-cost coverage and a projection/schema consistency guard. Preserve production behavior and all existing assertions except the authorized stronger error assertion.

Authorized by Filip: “please fix the issues you feel are real ones”. Run regression tests and full scoreboard gates before committing. Outcome: 53 SQLite/PostgreSQL tests pass, including anonymous public history across both submitters, each corrupt money field, structured SQLSTATE checks and schema/projection parity. Full PostgreSQL CI selection: 62 passed. The CI job keeps this suite explicitly registered, away from the other pending additions. All scoreboard gates green. No production-code changes in this follow-up.

CI registration is separated from the other pending PostgreSQL suites so their additions can merge without dropping tests. The exact workflow selection and all scoreboard gates pass after this adjustment.

## Closure — 2026-11-05

User authorized the final review and squash merge. Merged [PR #1626](https://github.com/ScreamingFace/screamingface/pull/1626)
as `b972231dafc92f975bd43445bdd50f5015bdabe2`. Approval and green CI covered the unchanged PR head.

Final verification combined all three approved changes with current main: full
scoreboard and repository gates passed; 217 focused SQLite/PostgreSQL regressions
passed with no skips (local PostgreSQL 15, CI PostgreSQL 17). This included metadata,
Unicode/non-finite validation, corrupted costs, migrations and concurrency.
Subsequent concurrent main changes were confined to Engine code/docs; scoreboard
paths still matched the tested sequence before the last merge.

Sergio approved with nits. Shared decoding also omits malformed provider rows and uses the submitter fallback for malformed authors on SQLite. This non-money behavior remains a non-blocking review note; stored/export data is unchanged.

Linear is Done with the merge and validation evidence recorded. No production
release was performed and no visual owner check is needed for these changes.

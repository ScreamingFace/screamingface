---
ticket: OME-1517
stack: scoreboard
status: in_progress
started: 2026-10-30
finished:
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

Implementation complete; review/merge pending.

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

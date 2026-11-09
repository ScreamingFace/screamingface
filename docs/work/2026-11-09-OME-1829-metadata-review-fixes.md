---
ticket: OME-1829
stack: scoreboard
status: done
started: 2026-11-09
finished: 2026-11-09
---

# Review corrections

## Intent

Correct import ordering, reject display controls and unstorable Unicode in provenance, and keep rejected private attribution out of CLI errors.

## Planned changes

Keep the row update and timestamp write in one transaction. Compute a nondecreasing timestamp after the upsert lock, at least the first-import time. Reject Unicode Cc/Cf/Cs in metric and attribution before trimming. Format validation diagnostics without rejected inputs or exception context. Add first-import, backward-clock, concurrent replacement, public/private read and CLI regressions.

## Test plan

New regression tests first; run on isolated SQLite and PostgreSQL databases. All prior tests remain unchanged. Run scoreboard gates and inspect the final diff.

## Acceptance

All reported defects covered, previous contracts preserved, no schema or dependency changes, correct GitHub identity on each write.

## Outcome

All three findings reproduced before the fixes. New cases initially failed for first-import ordering, all four PostgreSQL overlap scenarios, display controls/public reads, and CLI privacy. Corrected timestamp generation under one transaction, Unicode label validation and redacted CLI diagnostics. Updated operator docs and registered new/existing baseline tests in the PostgreSQL CI job.

Validation: 54 focused SQLite cases passed (four PostgreSQL-only cases skipped); all 58 passed on isolated PostgreSQL 15. Full scoreboard gate runner green including append-only check against the reviewed head, lint, format, types, full coverage suite and registered portal tests. The first full run caught missing CI registration; fixed and reran all gates. Existing tests were not modified.

Wisdom review: no schema/dependency change; one extra timestamp save holds the upsert lock until commit and clamps against prior/creation times. Shared provenance validation protects reads as well as imports; invalid private attribution no longer appears in error text or chained traceback. No UI/product-policy change.

Commit: fix(scoreboard): correct external import timestamps and validation (this commit).
Deviations: continued the existing PR head in a new isolated worktree; Linear unchanged per owner preference. PostgreSQL 15 locally; hosted CI uses its configured PostgreSQL service.

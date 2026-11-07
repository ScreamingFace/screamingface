---
ticket: OME-969
stack: scoreboard
status: done
started: 2026-10-30
finished: 2026-11-05
---

# Bound score submission metadata

## Intent

Apply the existing baseline metadata limits to public score submissions: at most
4096 serialized bytes and four levels deep. Authorized with OME-430 and OME-1517
on 2026-10-30; each receives a separate fix and PR.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/schemas.py`: reuse `_validate_bounded_metadata`
  in ScoreSubmission without changing baseline behavior.
- New request/schema regression tests for boundaries, nested lists, Unicode,
  normal metadata and no writes on rejection.
- Spec, plan and issue mirror.

## Test plan

Demonstrate oversized/deep requests accepted before the change. Assert field-specific
422 afterward, accepted exact boundaries and ordinary metadata round trips. Run all
scoreboard gates and existing baseline regressions.

## Acceptance

Over-limit metadata is rejected before storage. Reuse one definition of limits.
Existing valid requests and baseline import/read validation are unchanged.

## Outcome

Implementation merged; see closure below. Actual files match the plan.

- RED: five over-limit requests accepted; eight valid controls passed.
- GREEN: all 13 new HTTP tests pass. Combined new/baseline selection: 27 passed.
- Full scoreboard gates green: append-only tests, Ruff, formatting, Pyright,
  pytest/coverage, and portal Node tests. Existing tests unchanged.
- Commit: `fix(scoreboard): bound metadata on score submissions`.
- No migration or new dependency; no deviations.

## Wisdom review

One field validator calls the existing helper, preserving the baseline's exact
serialization and depth definitions. Tests prove both rejection without storage
and exact-boundary/Unicode round trips. No authentication, export, ranking or
stored-row behavior changes. This complements the separate OME-1658 Unicode PR;
both metadata validators must be retained when the branches are combined.

## Review follow-up — 2 November 2026

Reject excessively nested metadata without recursion errors, and bound the expanded numeric JSON representation on public submissions while preserving existing baseline budgets. Keep both metadata validators when combined with OME-1658 by using separate insertion points. Verify raw HTTP nesting, positive/negative exponents, exact boundaries, and database persistence on SQLite/PostgreSQL.

Authorized by Filip: “please fix the issues you feel are real ones”. Run regression tests and full scoreboard gates before committing. Outcome: 26 cross-backend review regressions pass, including exact 4096-byte PostgreSQL JSONB text storage, exponent expansion, safe deep-input errors and non-finite numbers. Original metadata/baseline tests remain green in the full gate run. Full PostgreSQL CI selection: 35 passed. All scoreboard gates green. No dependency or schema change. A route wrapper removes only unsafe metadata error inputs; OME-1658 retains responsibility for other Unicode validation errors.

## Second review follow-up — 2 November 2026

Sanitize every validation error located at body.metadata, including wrong-type and size failures, by omitting only its input. Keep error type, location, context and messages, and preserve unrelated inputs. Reproduce oversized and wrong-type metadata containing NaN/Infinity and test both databases.

Authorized by Filip: “Check these reviews and fix if you see fit”. Capture failing regressions first, then run focused SQLite/PostgreSQL tests, scoreboard gates and combined-branch verification. Outcome: 20 new cross-backend cases failed before the fix. All 46 metadata review tests now pass on SQLite/PostgreSQL, and the complete PostgreSQL CI selection passes (55 tests). Full scoreboard gates green. Every body.metadata error omits input while preserving its type/location/context; unrelated errors retain their input. No schema or dependency changes.

## Closure — 2026-11-05

User authorized the final review and squash merge. Merged [PR #1623](https://github.com/ScreamingFace/screamingface/pull/1623)
as `49d0d5312966d377caa3f0e8526314687394e1b0`. Approval and green CI covered the unchanged PR head.

Final verification combined all three approved changes with current main: full
scoreboard and repository gates passed; 217 focused SQLite/PostgreSQL regressions
passed with no skips (local PostgreSQL 15, CI PostgreSQL 17). This included metadata,
Unicode/non-finite validation, corrupted costs, migrations and concurrency.
Subsequent concurrent main changes were confined to Engine code/docs; scoreboard
paths still matched the tested sequence before the last merge.

Sergio approved with nits. Baseline accept/reject limits stay the same, but excessive depth now reports metadata_too_deep; this error-contract difference is an accepted deviation. Main already includes the general non-finite validation-input handler from PR #1620.

Linear is Done with the merge and validation evidence recorded. No production
release was performed and no visual owner check is needed for these changes.

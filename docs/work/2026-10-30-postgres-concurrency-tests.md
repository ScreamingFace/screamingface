---
ticket: OME-430
stack: scoreboard
status: done
started: 2026-10-30
finished: 2026-11-05
---

# Enable PostgreSQL concurrency regressions

## Intent

Repair the shared database fixture and run the existing concurrency tests on real
PostgreSQL in CI. Filip explicitly authorized this fixture/test-infrastructure fix
on 2026-10-30 as one of three requested tickets.

## Planned changes

- `apps/scoreboard/tests/conftest.py`: resolve the synchronous schema fixture before
  entering the async ORM fixture, preserving existing synchronous users.
- CI: include the existing two concurrency test node IDs and a new migration-chain
  regression in the existing PostgreSQL job.
- New fixture/isolation regression tests, migration check, and exact-file fixture
  transition approval record under `.claude/test-change-approvals/OME-430.json`.
- Spec/plan and existing task mirror.

## Test plan

Run the existing concurrency tests against a disposable PostgreSQL database to
reproduce the active-loop error. Then verify they pass without changing assertions,
check fresh schema isolation, and run the real migration chain followed by an
assertion that the content_hash unique index exists. Run all scoreboard gates and
the full PostgreSQL CI selection.

## Acceptance

Both original race tests run and pass in PostgreSQL CI. SQLite and synchronous
schema consumers still work; schema cleanup is retained. No application changes.

## Outcome

Implementation merged; see closure below.

- RED: both original race tests failed before their bodies with nested asyncio.run.
- A second fixture issue surfaced after that fix: tortoise_test_context attempts
  database creation. Replaced it with an isolated TortoiseContext using the
  already-provisioned schema, so no database-creation privilege is needed.
- GREEN: both original race tests and three new isolation/migration checks pass.
  Full PostgreSQL CI selection: 14 passed. Local PostgreSQL 15; CI PostgreSQL 17.
- Full scoreboard gates green, including the exact-file approval for the
  explicitly authorized fixture edit. Existing test assertions remain untouched.
- Real migration chain successfully creates a unique content_hash index.
- Commit: `test(scoreboard): enable PostgreSQL concurrency regressions`.
- No application/schema changes or new dependencies.

## Wisdom review

The original suggested async conversion would break synchronous schema-fixture
users. Resolving the existing synchronous fixture first preserves both caller
styles. TortoiseContext still provides per-test model/connection isolation; only
the task-owned schema is dropped. The test-helper database creation was an
additional setup failure exposed by running the previously dead tests, and is
fixed within the same authorized scope. Reused the existing CI service instead
of adding another job.

## Review follow-up — 2 November 2026

Use PostgreSQL index catalog attributes instead of matching rendered index SQL. Prove partial/non-unique indexes cannot satisfy the check; retain real migration coverage. Correct the obsolete concurrency-test comment without changing its assertions.

Authorized by Filip: “please fix the issues you feel are real ones”. Run regression tests and full scoreboard gates before committing. Outcome: The old LIKE query incorrectly accepted both partial and expression indexes (two failing negative controls). The catalog query now rejects both, composite and non-unique indexes, and accepts the valid unique content_hash index. Ten focused PostgreSQL tests pass; full PostgreSQL CI selection: 19 passed. All scoreboard gates green. Only the stale comment changed in the original concurrency test; its assertions are intact.

CI registration is separated from the other pending PostgreSQL suites so their additions can merge without dropping tests. The exact workflow selection and all scoreboard gates pass after this adjustment.

## Closure — 2026-11-05

User authorized the final review and squash merge. Merged [PR #1625](https://github.com/ScreamingFace/screamingface/pull/1625)
as `4b2ca3e656f52d6b0ed721e48203013a6ae71cbe`. Approval and green CI covered the unchanged PR head.

Final verification combined all three approved changes with current main: full
scoreboard and repository gates passed; 217 focused SQLite/PostgreSQL regressions
passed with no skips (local PostgreSQL 15, CI PostgreSQL 17). This included metadata,
Unicode/non-finite validation, corrupted costs, migrations and concurrency.
Subsequent concurrent main changes were confined to Engine code/docs; scoreboard
paths still matched the tested sequence before the last merge.

Dmitry and Sergio approved. The suggested stronger guard against future CI skips remains non-blocking.

Linear is Done with the merge and validation evidence recorded. No production
release was performed and no visual owner check is needed for these changes.

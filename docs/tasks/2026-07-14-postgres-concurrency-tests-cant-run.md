---
id: OME-430
linear_url: https://linear.app/openmined/issue/OME-430/scoreboard-postgres-concurrency-tests-cant-run-asynciorun-inside-an
status: in_progress
type: task
priority: P2
labels: [scoreboard, agentic, autonomous]
created: 2026-07-14
closed:
---

Found while addressing PR #390 review (OME-391): `postgres_schema_database_url` in
`apps/scoreboard/tests/conftest.py` calls `asyncio.run()` from inside an already-running
pytest-asyncio event loop, which raises immediately — and CI never sets
`SCOREBOARD_TEST_DATABASE_URL` anyway, so the two `test_postgres_concurrent_*` tests in
`test_store.py` have only ever skipped, never actually run.

Fix: convert the fixture to async, add a `postgres:16` CI service, and ideally a
migration-chain-vs-model-drift check (assert `content_hash`'s unique index exists after
running real migrations, not `generate_schemas()`). See the Linear issue for full detail.

Implementation: retain synchronous schema URL callers, resolve that fixture before
entering the async ORM context, and reuse the existing PostgreSQL 17 CI job.
Ledger: `docs/work/2026-10-30-postgres-concurrency-tests.md`.

# PostgreSQL concurrency coverage — OME-430

The existing race tests must execute in the PostgreSQL CI job instead of skipping
or failing before their bodies run. Keep their assertions intact. The shared ORM
fixture must initialize inside pytest's async loop while synchronous schema
creation/cleanup runs outside it. Preserve sync callers of the schema URL fixture.
Test isolation must remain per-test; do not drop a shared database.

Use the existing PostgreSQL 17 CI service. Add a real migration-chain smoke test
and verify the unique content_hash index independently of generate_schemas.

## Review follow-up — 2 November 2026

Use PostgreSQL index catalog attributes instead of matching rendered index SQL. Prove partial/non-unique indexes cannot satisfy the check; retain real migration coverage. Correct the obsolete concurrency-test comment without changing its assertions.

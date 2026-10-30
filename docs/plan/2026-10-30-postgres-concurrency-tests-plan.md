# PostgreSQL test implementation — OME-430

1. Reproduce the two existing race tests failing during fixture setup on PostgreSQL.
2. Add a synchronous URL-selection fixture and inject it into the async ORM fixture.
3. Add isolation/migration regressions; register the tests in the existing CI job.
4. Run SQLite gates and PostgreSQL selection; record the exact authorized fixture
   transition without weakening old tests.
5. Review, record outcomes, commit and open a linked PR.

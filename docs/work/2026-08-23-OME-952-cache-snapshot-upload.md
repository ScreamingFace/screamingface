---
ticket: OME-952
stack: aigateway
status: in_review
started: 2026-08-23
finished:
---

# OME-952 — aigateway: cache-snapshot upload routes and loader

## Intent

Implement the gateway half of the approved OME-951 spec: admin routes that accept a
`snapshot-cache` pg_dump, an async single-slot job runner, a COPY/merge Postgres loader, and
the revision guard — never executing uploaded SQL.

## Planned changes

See `docs/plan/2026-08-23-OME-952-cache-snapshot-upload.md` (9 files + 4 test modules).

## Test plan

See the plan's Tests section: slicing unit tests, job-runner state machine with fake loader,
route auth/serialization tests, Postgres integration test (testcontainers).

## Acceptance

Spec acceptance criteria 1–8, 10–11 (12 belongs to OME-954's manifest emission).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the regression test for the slicer's terminator latch
- **Commits:** (see PR)
- **Gates:** ruff clean · pyright clean · check_no_enterprise OK · pytest 3755 passed / 54 skipped, coverage 92.28% · AIGW_TEST_PG=1 integration 5 passed
- **Deviations:** (1) merge SQL includes `id` in the target list with `gen_random_uuid()` and sets `updated_at = now()` — the live table has NO db-side defaults (verified against the running cluster), so the INSERT must generate them. (2) Two defects found and fixed by the Postgres integration run: the slicer leaked the dump epilogue into COPY across batch boundaries (pg_dump 18 epilogue parses as an empty-uuid row), and the merge column list was one short. Both carry regression tests.

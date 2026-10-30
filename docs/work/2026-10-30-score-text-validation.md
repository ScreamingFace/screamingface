---
ticket: OME-1658
stack: scoreboard
status: in_progress
started: 2026-10-30
finished:
---

# Safe score text and validation errors

## Intent

Reject NUL and lone surrogates in author, paper URL and free-form metadata fields
before storage, and keep all request-validation responses encodable as JSON.
Scope approved by Filip's go-ahead on 2026-10-30.

## Planned changes

- Reuse `scores/credit_metadata.py` text checks from `scores/schemas.py` on submit/edit.
- Add an exception handler in `validation.py`, registered in `main.py`.
- Add `tests/unit/test_score_text_validation.py` with SQLite/PostgreSQL request tests;
  register it in the existing PostgreSQL CI job.
- Spec, plan and task mirror for this unit.

## Test plan

Reproduce rejected-input responses becoming 500, and unsafe text reaching storage.
Cover submit, same-owner resubmit, PATCH, nested metadata keys/values, wrong shapes,
normal Unicode, valid surrogate pairs and unchanged ordinary 422 responses. Verify
rejections do not create scores or metadata-edit events. Run scoreboard gates and
PostgreSQL integration checks against an isolated local database.

## Acceptance

The ticket examples return field-specific 422 on both backends, never 500/503.
Valid requests and normal validation responses retain their existing behavior.
No storage schema changes or migration; no new metadata size/depth policy (OME-969).

## Outcome

Implementation complete; review and merge remain pending.

- Added shared validation of text, nested JSON keys and values, used by author
  lists, paper URLs and submission metadata. Submit and PATCH share credit checks.
- Registered a request-validation handler that uses FastAPI unchanged for normal
  responses and ASCII JSON escapes when rejected input cannot encode as UTF-8.
- Added 75 request regressions across SQLite/PostgreSQL and registered the module
  in the PostgreSQL CI job. Rejected submissions and edits leave rows/events intact.
- RED: 60 failures and 15 passing controls on the original implementation.
- GREEN: all 75 new cases pass; the full PostgreSQL CI selection passes (84 tests).
- `uv run .claude/scripts/run_gates.py scoreboard`: all gates green (append-only
  tests, Ruff lint/format, Pyright, full pytest suite with 80% coverage floor,
  and portal Node tests). Existing tests remain unchanged.
- Commit message: `fix(scoreboard): reject unstorable score text and encode validation errors`.

### Wisdom review

The existing text definition is reused, with no new dependency, schema change or
migration. Ordinary validation responses remain byte-for-byte compatible. The
handler catches only Unicode encoding errors and preserves the original error
structure. Authentication and public artifact rules are unchanged. Tests exercise
HTTP responses and verify persisted state, including failed resubmissions/edits.

### Deviations

No scope changes. The test fixture isolates Tortoise's SQL executor cache because
its keys omit the backend; otherwise switching SQLite to PostgreSQL reuses SQLite
placeholders. This is test-only. Free-form metadata remains unsupported by PATCH,
as on main; its validation runs during submission. Existing bad rows are not
rewritten. Local database checks used PostgreSQL 15; CI uses PostgreSQL 17.

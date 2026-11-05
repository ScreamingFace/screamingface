---
ticket: OME-1658
stack: scoreboard
status: done
started: 2026-10-30
finished: 2026-11-03
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

## Review follow-up — structural error-input assertion

Authorized by Filip on 2026-10-30: improve the existing test in PR #1620.

Plan: replace the serialized substring check with strict UTF-8 decoding and JSON
parsing, select the error at its expected location, and compare its input to the
expected object (or the invalid field-name string for Pydantic's body-root error).
Record the exact authorized test edit for the append-only gate. Verify normal
SQLite/PostgreSQL cases and demonstrate that losing the echoed input fails the
new assertion even if the serialized response still contains the surrogate escape.
Run scoreboard gates before committing. No production behavior changes.

Follow-up outcome: all 75 validation tests passed across SQLite and PostgreSQL.
A temporary mutation replaced the error input while preserving an unrelated
surrogate escape: the old substring assertion still passed, and all six targeted
cases failed on the new input comparison as expected. All scoreboard gates passed
(lint, formatting, type checks, Python tests/coverage, and portal tests).

## Second review follow-up — 2 November 2026

Prevent non-finite floats echoed in any validation error input from causing JSONResponse to return 500. Remove only inputs containing non-finite numbers, using bounded-stack iterative inspection; preserve finite inputs and Unicode escape behavior. Cover score/integer/unknown-field errors, nested NaN/Infinity, and combined Unicode/non-finite errors on both databases. Do not broadly catch unrelated ValueError failures.

Authorized by Filip: “Check these reviews and fix if you see fit”. Capture failing regressions first, then run focused SQLite/PostgreSQL tests, scoreboard gates and combined-branch verification. Outcome: 20 new cross-backend cases failed before the fix. All 95 text/error regressions pass on SQLite/PostgreSQL; the complete PostgreSQL CI selection passes (104 tests). Full scoreboard gates green. The mixed-error control proves ordinary strings, finite numbers, nested finite values and lone-surrogate inputs survive unchanged while the non-finite input is omitted. No broad exception catch, schema change or dependency change.

## Closure — 2026-11-05

Merged [PR #1620](https://github.com/ScreamingFace/screamingface/pull/1620) on 2026-11-03 as
`706a790fa984db16d7c06c4d64de3716c2e73428`. Linear is Done.

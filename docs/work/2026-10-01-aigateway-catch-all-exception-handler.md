---
ticket: OME-939
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# aigateway-catch-all-exception-handler — class-name-only catch-all 500 with the call id

## Intent

An exception that escapes every route today becomes an uncaught ASGI 500: Starlette's plain-text
"Internal Server Error", no aigateway log line, no `gateway_call_id`, no audit. Register a catch-all
`Exception` handler that emits exactly one sanitized record (exception CLASS name only, method,
path, status 500) carrying the request's `gateway_call_id` + `trace_id`, and returns a structured
JSON 500 that names the call id. Audit parity with `routes/admin.py` `_audit` (4xx/5xx recorded as
diligently as successes).

Subtlety that shapes the design: Starlette dispatches an `Exception` handler from
`ServerErrorMiddleware`, which sits OUTSIDE every user middleware — so by the time the handler runs,
`CallIdMiddleware`'s `call_scope` has already unwound and the contextvar is empty. The ids survive on
`scope["state"]` (published there by the middleware), so the handler re-binds `call_scope` from them
before logging; the record factory then stamps them like any other line.

## Planned changes

- `apps/aigateway/src/aigateway/unhandled_errors.py` (new) — the handler. Own module because
  `main.py` is already 485 lines.
- `apps/aigateway/src/aigateway/main.py` — one `add_exception_handler(Exception, …)` line.
- `apps/aigateway/tests/unit/test_unhandled_exception_handler.py` (new).

## Test plan

- An unhandled exception in a route → status 500, JSON `{"detail": {"code": "gateway_internal_error", ...,
  "gateway_call_id": <id>}}`, `x-aigw-trace-id` echoed.
- Exactly one `aigateway` ERROR record for it; it carries the same `gateway_call_id` as the body; it
  names the exception class; the exception's message text is absent; `exc_info` is None.
- An `HTTPException` (already accounted by `_accounted_http_exception`) is NOT re-wrapped: its status
  and body stand and the handler logs nothing.
- Handler direct-call with no published ids (defensive): still returns the structured 500, no id key.

## Acceptance

- Behaviour tests above green; `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the owner-approved assertion change in
  `apps/aigateway/tests/unit/test_profile_resolution_characterisation.py`, its approval record
  `.claude/test-change-approvals/OME-939.json`, and the `docs/tasks` mirror → `in_review`.
- **Commits:** see the PR (single commit, `feat(aigateway): …`).
- **Gates:** `run_gates.py aigateway --skip-append-only` all green. The append-only check is red
  ONLY on the approved file: the Python checker has no approval path (`approved_test_changes.py`
  exempts TS/TSX only), so the approved transition is pinned by blob in the manifest instead.
- **Deviations:**
  - First pass BLOCKED on the append-only conflict (prior characterisation test pinned the bare
    `"Internal Server Error"` 500). Owner decision 2026-10-01 (Sergey Bershadsky): approved,
    assertion only — that test's docstring still describes the legacy page and was deliberately
    left untouched (no other edits allowed).
  - Uvicorn's duplicate traceback NOT suppressed. Starlette re-raises after the handler; the only
    clean alternative (a non-re-raising catch-all inside the app) would also swallow exceptions
    `test_a_persistent_index_fault_at_the_resolver_read_escapes_the_route` pins as escaping — a
    second prior contract the owner did not approve changing. Documented in the module AIDEV-NOTE.
  - Linear stayed in Backlog during the work (lane rule: only In Review + PR link).

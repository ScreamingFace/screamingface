---
ticket: OME-968
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# dispatch-terminal-failure-record — every chat dispatch failure emits one attributable record

## Intent

A mapped provider failure (a litellm `APIConnectionError` → 5xx `provider_unavailable`, a plugin
`HTTPException`) returns an error to the caller and logs NOTHING at WARNING+; a failed stream logs
only the exception and plugin class at HTTP 200. Every terminal failure on the chat dispatch path —
mapped HTTPException, mapped litellm family, unclassified exception, response-conversion failure,
and a mid-stream failure — must emit exactly one structured record carrying `gateway_call_id`
(stamped by the OME-938 record factory), the failure classification (`detail.code`), provider and
status. Class-name-only posture: no provider text, prompts or tracebacks. No LiteLLM callbacks.

Scope boundary (coordinator): mapped exceptions + streaming failures on the dispatch path. Pre-
dispatch 4xx (malformed JSON, unknown provider) and unhandled non-dispatch exceptions (OME-939) are
out of scope; success/completion lines are OME-1154.

## Planned changes

- `apps/aigateway/src/aigateway/routes/chat_dispatch.py` — `log_dispatch_failure` emitted inside
  `_safe_dispatch_failure_response` (the one funnel all three mapped branches already pass through);
  `_stream` gains an optional `provider` and its existing `stream failed` line gains
  `provider/classification/status`; `convert_provider_response` gains an optional `provider` and its
  existing line gains the same fields.
- `apps/aigateway/src/aigateway/routes/chat.py` — the unclassified branch's own `unhandled dispatch
  error` line folds into the funnel (passes `error_type`) so the request still yields ONE record;
  pass `provider` to `_stream` / `convert_provider_response`.
- `apps/aigateway/tests/unit/test_dispatch_failure_records.py` (new).

## Test plan

Driven through the real app (anthropic connection, dispatch patched), records captured on the
`aigateway` logger:
- litellm `APIConnectionError` → exactly one WARNING+ record; carries the request's call id (equal
  to `_aigw.gateway_call_id` in the body), `classification=<detail.code>`, `provider=anthropic`,
  `status=<response status>`; level ERROR for 5xx; provider text absent; `exc_info` None.
- plugin `HTTPException(429 rate_limited)` → one WARNING record, status 429.
- unclassified `RuntimeError` → exactly one record (not two), `classification=provider_error
  status=502 type=RuntimeError`, call id present.
- conversion failure → one record with provider + `status=502`.
- streaming failure → one record, carries a call id and the response's `x-aigw-trace-id`,
  `provider=anthropic classification=provider_error status=200`.

## Acceptance

- Tests above green; prior tests untouched and green; `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`chat_dispatch.py`, `chat.py`, new `test_dispatch_failure_records.py`)
  plus the `docs/tasks` mirror → `in_review`.
- **Commits:** see the PR (single commit, `fix(aigateway): …`).
- **Gates:** `run_gates.py aigateway` — ALL GATES GREEN (append-only check, ruff, format, pyright,
  no-enterprise, pytest + coverage ≥80%).
- **Deviations:** (1) the unclassified branch's separate `unhandled dispatch error` line is folded
  into the single `dispatch failed … type=<Class>` record, so the request still yields ONE record —
  any dashboard grepping the old phrase must move to `dispatch failed`. (2) Rare double failure
  (the failure-marking step itself raises) yields its pre-existing `dispatch failure handling error`
  diagnostic PLUS the terminal record. (3) Linear stayed in Backlog during the work (lane rule: the
  only Linear change is In Review + PR link). (4) Based on origin/main, not OME-939: 939 is blocked
  and touches different code (app-wide handler vs dispatch funnel).

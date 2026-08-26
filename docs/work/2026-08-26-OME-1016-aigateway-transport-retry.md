---
ticket: OME-1016
stack: screamingface-engine
status: in_progress
started: 2026-08-26
finished:
---

# OME-1016 — Retry aigateway transport failures in benchmark grading

## Intent

A transient `httpx.ReadError` on the runner→aigateway hop during a judge call
surfaces as `grading · draco_grading_failed · cases N, M — ReadError('')` in the
report. Two defects combine: (1) the connector lets `httpx.TransportError`
escape raw, so the benchmark's declared `retry=` policy (OME-993) never fires
for transport errors — only `Url4Error` is retried; (2) the error carries no
`code`, so `public_error` falls back to the opaque benchmark default
`draco_grading_failed`, and the message is `ReadError('')` because `str(exc)`
is empty. Concurrent judge calls that fail together on a gateway blip also
retry in lockstep — a retry storm against a recovering aigateway.

**Constraint: `packages/url4` is untouchable and must stay agnostic to the
screamingface/aigateway use cases.** This unit therefore retries and translates
transport errors entirely in the screamingface-engine connector: a bounded
backoff retry for `httpx.TransportError`, then a retryable
`ResolutionError(code="aigateway_transport_error")` with a non-empty message.
The benchmark's `retry=` (url4) stays as the second layer for HTTP-status
failures and for a sustained outage.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner/connector.py` —
  `_fetch_completion` posts go through a `_post_completion` helper that retries
  `httpx.TransportError` with exponential backoff + jitter (module constants,
  `_TRANSPORT_RETRIES = 1`) and then raises
  `ResolutionError(code="aigateway_transport_error", permanent=False)` with a
  non-empty message (`_transport_detail`).
- Tests: `apps/screamingface-engine/tests/unit/test_aigateway_connector.py`
  (transport-error translation + retry-then-succeed),
  `apps/screamingface-engine/tests/unit/test_grading_error_integrity.py`
  (judge ReadError → retry fires → graded; exhausted →
  `aigateway_transport_error` + `retryable=True`).

## Test plan

- Connector unit: a `httpx.MockTransport` raising `httpx.ReadError("")` →
  `ResolutionError` with `code="aigateway_transport_error"`, `permanent=False`,
  non-empty message; a flaky transport (fail once, then succeed) → the call
  succeeds after one retry (2 POSTs).
- Engine grading-integrity: a judge world whose gateway raises `ReadError` on
  the first judge post then answers a valid verdict → the case is graded
  (retry fired); a world that always raises → the case failure is
  `stage=grading`, `code=aigateway_transport_error`, `retryable=True`,
  candidate output preserved.

## Acceptance

- A judge transport failure is retried (connector backoff) and, if still
  failing, renders as `aigateway_transport_error` with `retryable=true` and a
  non-empty message — never the opaque `draco_grading_failed` fallback.
- `packages/url4` is untouched; the benchmark protocol text is unchanged (no
  revision bump, no cache-key invalidation).
- All gates green for `screamingface-engine`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `runner/connector.py` (transport retry +
  translation), `test_aigateway_connector.py` (2 tests),
  `test_grading_error_integrity.py` (2 tests + `_judge_transport_world`
  helper), plus the four docs. `packages/url4` untouched.
- **Commits:** `3faaedfc` — fix(screamingface-engine): retry aigateway
  transport failures in grading
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine` —
  ALL GATES GREEN (ruff check, ruff format, pyright, check_layering, pytest
  --cov-fail-under=80). Full unit suite: 2036 passed, 5 skipped.
- **Deviations:** Level 2 (url4 `GuardNode` backoff) was dropped after the
  constraint that `packages/url4` is untouchable; the backoff retry moved
  into the connector (`_post_completion`), with the benchmark's `retry=`
  remaining a second layer for HTTP-status failures and sustained outages
  (bounded at 2×3 = 6 POSTs per judge call).

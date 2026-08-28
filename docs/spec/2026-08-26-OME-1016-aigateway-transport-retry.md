# OME-1016 — Spec: retry aigateway transport failures in benchmark grading

## Problem

A transient `httpx.ReadError` on the runner→aigateway hop during a judge call
renders as `grading · draco_grading_failed · cases N, M — ReadError('')`.

Three defects combine:

1. **Retry never fires for transport errors.** The connector's
   `_fetch_completion` (`apps/screamingface-engine/src/screamingface_engine/
   runner/connector.py`) has no try/except around `http_client.post`, so an
   `httpx.ReadError` escapes raw. The benchmark's declared `retry=2` (OME-993)
   retries only `Url4Error` — a raw transport error bypasses it.
2. **No error code.** `httpx.ReadError` has no `code` attribute, so
   `_error_payload` produces `{"error": {"kind": "ReadError", "message":
   "ReadError('')"}}` with no code, and `public_error` falls back to the
   benchmark default `draco_grading_failed`.
3. **Useless message.** `str(ReadError(''))` is empty, so `_error_payload`
   falls back to `repr(exc)` → `ReadError('')`.
4. **No backoff.** Concurrent judge calls that fail together on a gateway blip
   retry in lockstep — a retry storm against a recovering aigateway
   (api-expert: "Never retry in parallel"; aigateway's own
   `with_overload_retry` already uses backoff + jitter).

## Constraint

**`packages/url4` is untouchable and must stay agnostic to the
screamingface/aigateway use cases.** The retry/backoff must live entirely in
the screamingface-engine connector. The benchmark's `retry=` (url4) stays as
the second layer for HTTP-status failures and for a sustained outage.

## Design

### The connector owns the transport retry (`runner/connector.py`)

`_fetch_completion`'s two `http_client.post` calls move behind a
`_post_completion` helper that:

1. Retries `httpx.TransportError` (the narrow network-layer tuple:
   `ReadError`, `ConnectError`, `ReadTimeout`, `WriteError`, `PoolTimeout` —
   all transient) with exponential backoff + jitter, bounded by
   `_TRANSPORT_RETRIES = 1` (two attempts).
2. After exhaustion, raises:

```python
ResolutionError(
    f"aigateway request failed at the transport layer: {_transport_detail(exc)}",
    code="aigateway_transport_error",
    permanent=False,
)
```

- `permanent=False` → `retryable=True` in the report.
- `_transport_detail` yields `ReadError` (class name) when `str(exc)` is
  empty, else `ReadError: <detail>`.
- Chained `from exc` so the original cause survives.
- `HTTPStatusError` is deliberately NOT caught — `_raise_for_status` handles
  non-2xx after the post returns.
- Backoff constants are module-level (`_TRANSPORT_BACKOFF_BASE_S = 0.5`,
  `_TRANSPORT_BACKOFF_MAX_S = 8.0`, `_TRANSPORT_BACKOFF_JITTER_S = 0.25`,
  matching aigateway's `RetryPolicy`) so tests can zero them.

### Interaction with the benchmark's `retry=` (url4)

The connector's retry is the transport retry; the benchmark's `retry=2`
remains the HTTP-status retry. In the common transient case the connector's
single retry succeeds and the url4 retry never fires. In a sustained outage
both layers fire — bounded at 2 connector attempts × 3 url4 attempts = 6
POSTs per judge call, backoff-spaced. This is accepted: bounded, rare, and
the judge call is idempotent-ish (aigateway's global cache replays an
identical retried request).

## Non-goals (Chesterton's Fence)

- Do NOT touch `packages/url4` (agnosticism constraint).
- Do NOT change `retry=2` / `retry=JUDGE_RETRIES` counts (would bump the
  protocol revision and invalidate seeded cache keys).
- Do NOT change `on_error="fail"` fan-outs (OME-924) or the
  `preserve_candidate_outcome` collect boundary.
- Do NOT retry on `Exception` — only `httpx.TransportError`.
- Do NOT add httpx transport `retries=` — httpx only retries connect errors,
  never `ReadError`.

## Tests

- Connector: `httpx.MockTransport` raising `httpx.ReadError("")` →
  `ResolutionError` with `code="aigateway_transport_error"`,
  `permanent=False`, non-empty message; a flaky transport (fail once, then
  succeed) → the connector retries and the call succeeds (2 POSTs).
- Grading integrity: judge world whose gateway raises `ReadError` once then
  answers a valid verdict → case graded (retry fired); always-raises world →
  failure is `stage=grading`, `code=aigateway_transport_error`,
  `retryable=True`, candidate output preserved.
- Backoff constants zeroed via `mock.patch` in tests for speed.

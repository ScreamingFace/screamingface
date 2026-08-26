# OME-1016 — Plan: retry aigateway transport failures in benchmark grading

## Constraint

`packages/url4` is untouchable (agnosticism). All changes live in
`apps/screamingface-engine`.

## Steps

1. **Connector transport retry + translation.** In
   `apps/screamingface-engine/src/screamingface_engine/runner/connector.py`:
   - Add `import asyncio` and `import random`.
   - Add module constants `_TRANSPORT_RETRIES = 1`,
     `_TRANSPORT_BACKOFF_BASE_S = 0.5`, `_TRANSPORT_BACKOFF_MAX_S = 8.0`,
     `_TRANSPORT_BACKOFF_JITTER_S = 0.25`.
   - `_post_completion` retries `httpx.TransportError` up to
     `_TRANSPORT_RETRIES` times with `_transport_backoff(attempt)` sleep, then
     raises `ResolutionError(code="aigateway_transport_error",
     permanent=False)` with a non-empty message.
   - Add `_transport_backoff(attempt)` (exponential + jitter) and
     `_transport_detail(exc)` (class name when `str()` is empty) helpers.
   - Replace both `http_client.post` calls in `_fetch_completion` with
     `_post_completion`.

2. **Connector tests.** In
   `apps/screamingface-engine/tests/unit/test_aigateway_connector.py`:
   - `test_aigateway_transport_errors_map_to_retryable_resolution_error`:
     always-raise `httpx.ReadError("")` → `ResolutionError` with
     `code="aigateway_transport_error"`, `permanent=False`, non-empty message.
   - `test_aigateway_transport_error_is_retried_then_succeeds`: fail once,
     then succeed → result returned, 2 POSTs observed.
   - Zero the backoff constants via `mock.patch` for speed.

3. **Grading-integrity tests.** In
   `apps/screamingface-engine/tests/unit/test_grading_error_integrity.py`:
   - `_judge_transport_world` helper: judge route raises `httpx.ReadError`
     (configurable: first N posts, or always), then answers a valid verdict
     `{"explanation": "evidence", "criterion_status": "MET"}`.
   - `test_a_judge_transport_error_is_retried_and_the_case_is_graded`: fail
     the first judge post → connector retry fires → case graded (score set,
     no failures).
   - `test_a_judge_transport_error_exhaustion_lands_as_aigateway_transport_error`:
     always raise → failure is `stage=grading`,
     `code=aigateway_transport_error`, `retryable=True`, candidate output
     preserved, never "Criterion envelope".
   - Zero the backoff constants via `mock.patch` for speed.

4. **Gates.** `uv run run_gates.py screamingface-engine` green.

## Files

- `apps/screamingface-engine/src/screamingface_engine/runner/connector.py`
- `apps/screamingface-engine/tests/unit/test_aigateway_connector.py`
- `apps/screamingface-engine/tests/unit/test_grading_error_integrity.py`
- docs: work ledger, task mirror, spec, plan (this file)

## Risks

- Double-retry with the benchmark's `retry=` in a sustained outage (2 × 3 = 6
  POSTs per judge call) — accepted: bounded, rare, backoff-spaced, and the
  judge call is idempotent-ish via aigateway's global cache.
- Connector translation changes the error surface for ALL aigateway calls
  (judge + candidate + tool-loop round trips) — strictly an improvement
  (retryable + meaningful code), covered by the connector unit tests.

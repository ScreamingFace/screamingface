---
ticket: OME-1170
stack: screamingface-engine
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1170 — Catalog upstream timeout survives a cold gateway (30s + one retry)

## Intent

On a freshly started stack, the engine's catalog fetch gives the gateway 10s, but a cold
datasheet composition measures 3–11.8s per model — so the first parameter check after boot
deterministically 504s for the slower models and the SDK surfaces a hard `PlanningError`.
Raise the upstream timeout to 30s (above the measured cold ceiling) and retry once on a
timeout (nearly free: the failed attempt warmed the gateway's cache), so a
first-evaluate-after-boot succeeds instead of failing.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/catalog/__init__.py` — raise
  `_UPSTREAM_TIMEOUT_S` 10.0 → 30.0 with a WHY comment carrying the measured cold-path numbers.
- `apps/screamingface-engine/src/screamingface_engine/catalog/aigateway.py` — `_request`
  retries once on `httpx.TimeoutException` before raising `CatalogUnavailable`.

## Test plan

- RED (in `tests/unit/test_catalog_aigateway.py`):
  - timeout then success → `fetch` returns the catalog; exactly 2 upstream requests.
  - timeout then success → `fetch_model_parameters` returns the datasheet (the route the bug
    actually hits); exactly 2 upstream requests.
  - persistent timeout → `CatalogUnavailable`; exactly 2 upstream requests (bounded — a down
    gateway fails within 2×timeout, never loops).
  - non-timeout transport error → no retry (1 request) — retry is timeout-only, because only
    a timeout implies "the slow attempt warmed the cache".
  - `_default_client` timeout is 30s, above the 11.8s measured cold maximum (guards the
    "don't optimize it back down" invariant).
- Prior tests untouched; `test_a_timeout_raises_catalog_unavailable` stays green (persistent
  timeout still classifies as `CatalogUnavailable`).

## Acceptance

- First fetch after a cold gateway (≤30s composition, or 10–12s + warm retry) succeeds.
- A down/hung gateway still fails as `CatalogUnavailable` within ~2×30s, never unbounded.
- Warm path untouched; all prior tests green; engine gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `docs/tasks/2026-09-10-OME-1170-catalog-timeout-retry.md`
  (issue mirror) and this ledger. Retry bound expressed as `_TIMEOUT_ATTEMPTS = 2` constant in
  `aigateway.py` (INVARIANT-commented) rather than a bare literal.
- **Commits:** (filled at PR) `fix(screamingface-engine): survive a cold gateway when fetching model parameters`
- **Gates:** run_gates.py screamingface-engine — ALL GATES GREEN (ruff check, format, pyright,
  check_layering, pytest 2678 passed / 9 skipped, coverage ≥80%). 5 new tests; prior tests
  untouched (append-only check green).
- **Deviations:** none.

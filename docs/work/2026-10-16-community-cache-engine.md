---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-16
finished: 2026-10-16
---

# community-cache-engine — proxy the community-cache pages through the Engine (epic OME-1311, PR 2/3)

## Intent

The hosted gateway has no public ingress, so a signed-in local engine reaches the community
cache through the hosted Engine (`fusion.dev.screamingface.ai`, behind Cloudflare Access). This
unit adds `GET /v1/cache/entries` to the Engine: it forwards the caller's verified identity, the
trace context and the query parameters to the gateway's route of the same path (PR 1, #1433 /
OME-1631), and streams the gateway's NDJSON page back as it arrives, still compressed, without
decoding or buffering it (a page can be ~235 MB of rows). Spec and plan:
`docs/spec/2026-10-15-community-cache.md` and `docs/plan/2026-10-15-community-cache.md`
(merged with #1433; decision 6 and "PR 2" are this unit).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/community_cache/port.py` (new) — the
  `CommunityCache` port, the `CachePage` value (status-free: an open, successful upstream
  stream) and a small error family with public HTTP mappings.
- `.../community_cache/aigateway.py` (new) — the AI Gateway adapter: a streamed `GET`, identity
  and `traceparent` forwarded the way `connections/aigateway.py` does, only the four known query
  parameters forwarded, gzip requested only when the caller accepts it, upstream failures mapped
  to the error family with the response closed.
- `.../community_cache/__init__.py` (new) — `build_community_cache(settings)`: `None` without
  `aigateway_base_url`; an `httpx` client whose read timeout bounds the gap between chunks, not
  the whole page.
- `.../rest/cache_entries.py` (new) — the route: 503 when not configured, problem+json errors,
  `StreamingResponse` over the raw upstream bytes with `Content-Type` / `Content-Encoding`
  passed through, `Cache-Control: private, no-store`, `Vary: Accept-Encoding, X-User-Email`,
  the upstream response closed when the stream ends or the client goes away.
- `.../app.py` — `community_cache` DI seam on `create_app`, router in `_ROUTERS`, hosted
  composition builds it and closes it on shutdown. Not the local Engine: the client pulls from
  the hosted Engine into its local gateway, so a local proxy of the local gateway serves nobody.
- No chart change: the route needs no setting beyond the existing `aigateway_base_url`.

## Test plan

- Adapter (httpx `MockTransport`): path and forwarded params (repeated `model` kept, unknown
  params dropped); identity forwarded and nothing else of the caller's headers; `traceparent`
  forwarded; `Accept-Encoding: gzip` only when asked, `identity` otherwise; the body is yielded
  as raw bytes (a gzip body arrives still compressed); `Content-Type` / `Content-Encoding`
  reported; 401 → rejected, 422 → invalid request, 5xx/other → bad gateway, timeout → 504,
  transport failure → 503, each closing the upstream response.
- Route (fake port): 200 streams the page bytes unchanged with the passed-through headers and
  the private cache headers; the caller's identity, params and gzip preference reach the port;
  503 when not configured; each error is problem+json with its status; the upstream page is
  closed after the stream.
- Composition: `build_community_cache` returns `None` without a gateway URL and an adapter
  with one.

## Acceptance

- `GET /v1/cache/entries` on the Engine returns the gateway's page byte for byte, compressed
  when the caller asked for gzip, without the Engine holding the page.
- The caller's verified identity is what the gateway sees; nothing else of the caller's headers
  is forwarded.
- `run_gates.py screamingface-engine` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `community_cache/{__init__,port,aigateway}.py`, `rest/cache_entries.py`,
  `app.py` (seam, router, hosted composition and shutdown; the two gateway-adapter `app.state`
  assignments moved into `_install_gateway_adapters` to stay inside ruff's PLR0915 statement
  limit), `schemas/openapi.py` (the `Community cache` tag), `.claude/scripts/check_layering.py`
  (`community_cache` named in `CONTROL_PLANE`). Tests: `test_community_cache_aigateway.py`,
  `test_rest_cache_entries.py`.
- **Commits:** `feat(screamingface-engine): proxy the community-cache pages to the gateway`.
- **Gates:** append-only, ruff, format, pyright, layering green; pytest 5,435 passed / 123
  skipped, coverage 96%, new modules 100%. One failure, environmental:
  `test_chart_render_tracing.py::test_the_template_refuses_too_when_schema_validation_is_skipped`
  needs `helm template --skip-schema-validation`, which the local helm v3.14.2 lacks (CI
  installs a current helm with `azure/setup-helm`); this unit touches no chart.
- **Deviations:**
  - No local-Engine wiring (dropped from the plan): the client pulls from the hosted Engine.
  - `community_cache` added to the layering gate's `CONTROL_PLANE`. Unlisted, it was a shared
    leaf and could not import `connections.port.Caller`; listing it is also the stricter rule
    (the run half may not import it), the same treatment `reaper` and `unclaimed` got (OME-890).
  - The OpenAPI tag is `Community cache`, not `Cache`: the API description already uses
    "cache" for the per-run response cache.
  - Query values are not validated on the Engine: the gateway owns the contract and its 422 is
    passed through as problem+json.

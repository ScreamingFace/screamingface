---
ticket: OME-1044
linear_url: https://linear.app/openmined/issue/OME-1044/store-and-serve-tavily-retrieval-results-in-the-global-cache
parent: OME-1043
stack: aigateway
status: in_progress
priority: 3
labels: [aigateway]
actor: agentic
who-acts: autonomous
created: 2026-08-31
closed:
---

# OME-1044 — Store and serve Tavily retrieval results in the global cache

## Context

The aigateway half of OME-1043. aigateway receives a *description* of a Tavily retrieval
request, derives the cache key itself, and stores an opaque result string. It never holds a
Tavily credential and never calls Tavily.

Spec: `docs/spec/2026-08-31-OME-1043-tavily-retrieval-cache.md`.
Plan: `docs/plan/2026-08-31-OME-1044-tavily-cache-gateway.md`.
Ledger: `docs/work/2026-08-31-OME-1044-tavily-retrieval-cache.md`.

## Scope

- Pure key: `TavilyRetrievalCacheKey`, `tavily_retrieval_key()`, target normalization, contract
  revision. Reuses the existing canonicalizer.
- Store: `TavilyRetrievalCacheStore` over `request_cache_entries` (`provider='tavily'`,
  `model=<tool>`, `prompt_hash=key_hash`, `expires_at=NULL`).
- Routes: `POST /v1/retrieval/tavily/cache/lookup` and `.../entries`. A miss is a `200` answer.
- Settings: `AIGW_TAVILY_RETRIEVAL_CACHE_ENABLED` — app default off, chart default on.
- Chart + `DEPLOYMENT.md`.

## Out of scope

- The Runner side (OME-1045).
- A migration, a TTL, a sweeper, a caller-facing opt-out.

## Definition of done

- Key is pure and identity-free; `excluded_domains` participates (leakage guard tested).
- Insert-only fill; a race answers `race_lost` without overwriting.
- Every failure is a bypass or `not_stored`, never an exception into the route.
- `Cache-Status` + `X-AIGW-Cache*` emitted so the Runner's existing parser reads them.
- aigateway gates green.

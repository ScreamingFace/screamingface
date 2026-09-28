---
ticket: OME-1045
linear_url: https://linear.app/openmined/issue/OME-1045/route-runner-tavily-calls-through-the-aigateway-retrieval-cache
parent: OME-1043
blocked_by: [OME-1044]
stack: screamingface-engine
status: todo
priority: 3
labels: [screamingface-engine]
actor: agentic
who-acts: autonomous
created: 2026-08-31
closed:
---

# OME-1045 — Route Runner Tavily calls through the aigateway retrieval cache

## Context

The Runner half of OME-1043. Consult the aigateway Tavily retrieval cache before every Tavily
call and fill it after a successful one. Tavily execution and the Tavily credential stay in the
Runner, unchanged.

Blocked by OME-1044 — the route must exist first.

Spec: `docs/spec/2026-08-31-OME-1043-tavily-retrieval-cache.md`.

## Scope

- New `runner/tavily_retrieval_cache.py`: the request-description builder plus a
  `TavilyRetrievalCache` client with `lookup()` / `fill()`.
- Reuses the existing aigateway `httpx.AsyncClient` held by `_ModelEndpoint` and the same
  `_headers(profile, identity_headers)`. No new pool, base URL, or config knob.
- `WebToolRuntime` gains one optional field: `cache: TavilyRetrievalCache | None`.
- `_tavily_search` / `_tavily_extract` get lookup-before and fill-after.

## Ordering rules

- Cache the **pre-truncation, post-exclusion-filter** string those two functions return today.
  Truncation stays in `append_tool_results`.
- **Only the success path fills.** `"no results"`, extraction failures, and every
  `f"{name} failed: {exc}"` string are never stored — those are produced above, in
  `_execute_tool`.

## Failure semantics

- Any lookup failure (timeout, 5xx, malformed body) degrades to a miss: narrow
  `except (httpx.HTTPError, ValueError)`, log, then call Tavily as today.
- Any fill failure is logged and ignored. Dedicated 5 s timeout, separate from Tavily's 30 s.
- No cache exception escapes into the tool loop; `CancelledError` propagates.

## Out of scope

- The aigateway side (OME-1044).
- In-run single-flight memo.

## Definition of done

- A hit returns the cached string and makes **no** Tavily request.
- Every cache failure mode still completes the run.
- Two different exclusion sets never read each other's row.
- Gateway cache disabled ⇒ behaviour byte-identical to today.
- The Tavily API key is never sent to aigateway (extend
  `test_tavily_key_never_sent_to_aigateway`).
- screamingface-engine gates green.

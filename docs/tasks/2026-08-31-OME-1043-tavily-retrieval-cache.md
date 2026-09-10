---
ticket: OME-1043
linear_url: https://linear.app/openmined/issue/OME-1043/cache-tavily-retrieval-results-in-aigateway
stack: aigateway
status: in_progress
type: epic
priority: 3
labels: [aigateway]
actor: agentic
who-acts: autonomous
created: 2026-08-31
closed:
---

# OME-1043 — Cache Tavily retrieval results in aigateway

## Context

Tavily retrieval runs in the Runner Job and never traverses aigateway, so it has no cache: an
identical request pays Tavily and the model again every run. The larger half of the cost is
second-order — the global cache hashes `messages` verbatim, so non-deterministic tool results
permanently poison the continuation chat call's key.

Spec: `docs/spec/2026-08-31-OME-1043-tavily-retrieval-cache.md`.

## Scope

Cross-cutting (D9): epic + one sub-issue per landing.

- **OME-1044** (`aigateway`) — the cache lane: server-derived key, store, two endpoints.
- **OME-1045** (`screamingface-engine`) — the Runner wiring; blocked by OME-1044.

**Note on labels:** the card's D9 says the epic carries all affected landing labels, but
Linear's landing group is single-select and rejected the pair. The epic therefore carries
`aigateway` only; `screamingface-engine` lives on OME-1045. The card is stale on this point.

## Out of scope

- Any aigateway → Tavily call, or a Tavily credential in aigateway.
- A migration, a new table, a TTL, or a sweeper.
- In-run single-flight; retrieval outcomes in run accounting.

## Definition of done

- Both sub-issues closed with their ledgers filled and gates green.
- A repeated identical retrieval is served from cache, and the tool-loop continuation chat call
  becomes cacheable because tool results are now byte-identical.

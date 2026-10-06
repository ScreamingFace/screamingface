---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-06
finished:
---

# e14-b2-engine-tavily-cache — route engine Tavily calls through the gateway retrieval cache

## Intent

OME-1045 (E14 PR B2, Refs OME-1307). The engine asks the aigateway Tavily retrieval cache before
each Tavily call and fills it after a successful one. Tavily execution and its key stay in the
engine. Replay of web search needs this, so B3 can count the lookup and fill outcomes.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/tavily_retrieval_cache.py` (new)
- `apps/screamingface-engine/src/screamingface_engine/world/web_tools.py` (cache field, lookup/fill)
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py` (build and pass the cache)
- `apps/screamingface-engine/tests/unit/test_tavily_retrieval_cache.py` (new)
- `apps/screamingface-engine/tests/unit/test_web_tools_tavily_cache.py` (new)

## Test plan

- Description builders: exact body for web_search and web_fetch; exclusions in the body; no key.
- `lookup`: hit, miss, bypass; timeout, 5xx, malformed body degrade to bypass; 5 s timeout.
- `fill`: stored, race_lost, not_stored; failure returns None; CancelledError propagates.
- `web_tools`: hit makes no Tavily request; miss then fill; no-results and extraction failure never
  fill; two exclusion sets send two descriptions; `cache is None` is unchanged.
- Connector: Tavily key never sent to the gateway (new test, covers the cache routes).

## Acceptance

- The OME-1045 definition of done holds; screamingface-engine gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

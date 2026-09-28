---
title: Store and serve Tavily retrieval results in the global cache
ticket: OME-1044
status: approved
date: 2026-08-31
spec: ../spec/2026-08-31-OME-1043-tavily-retrieval-cache.md
---

# Store and serve Tavily retrieval results in the global cache

1. Add failing tests under `apps/aigateway/tests/unit/tavily_retrieval/`:
   `test_tavily_retrieval_key.py` (purity — no identity input, no I/O; the exclusion-set
   leakage guard; `max_results` / `search_depth` discrimination; URL and query normalization
   including `utm_*` preservation; `web_fetch` ignoring the search-only fields) and
   `test_tavily_retrieval_store.py` (first-fill-wins → `race_lost`; infrastructure error →
   `not_stored`, never raising).
2. Implement `core/request_cache/tavily_retrieval.py`: `TavilyRetrievalCacheKey`,
   `TAVILY_RETRIEVAL_CONTRACT_REVISION`, target normalization, and `tavily_retrieval_key()`
   reusing the existing canonicalizer from `global_keys.py`.
3. Implement `core/request_cache/tavily_store.py`: `TavilyRetrievalCacheStore` over
   `request_cache_entries` (`provider='tavily'`, `model=<tool>`, `prompt_hash=key_hash`,
   `expires_at=None`), mirroring `TortoiseRequestCacheStore`'s exception discipline and clause
   ordering.
4. Add failing route tests in `tests/unit/tavily_retrieval/test_tavily_retrieval_routes.py`:
   hit / miss / bypass bodies and their `Cache-Status` + `X-AIGW-Cache*` headers; the five
   `422` validation refusals; `enabled=false` writes nothing; a fill on an existing key answers
   `race_lost` without overwriting.
5. Implement `routes/tavily_retrieval_cache.py` (both endpoints, `CurrentAccount`, the 256 KB
   result cap).
6. Wire the router and the store onto `app.state` in `main.py`.
7. **No configuration and no chart change** — the lane is unconditional (owner decision,
   2026-08-31). A drafted `AIGW_TAVILY_RETRIEVAL_CACHE_ENABLED` setting plus its
   `values.yaml`/`configmap.yaml` wiring was removed on instruction; a test pins that the
   store takes no gate so it cannot reappear.
8. Document the lane in `DEPLOYMENT.md` — what it stores, that `provider='tavily'` rows share
   the table, that the no-expiry contract still holds, that it is always on, and the
   per-provider reset.
9. Run the aigateway gates via `.claude/scripts/run_gates.py` (ruff, ruff format, pyright,
   check_no_enterprise, pytest with `--cov-fail-under=80`).
10. Review `origin/main...HEAD`, fill the ledger outcome, commit with `Refs: OME-1044`, push the
    branch and open the PR.

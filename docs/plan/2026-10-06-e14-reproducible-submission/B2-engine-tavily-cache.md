# B2 — engine: Tavily through the gateway retrieval cache (OME-1045)

- **Worktree:** `.claude/worktrees/e14-b2-engine-tavily-cache` · **Branch:** `e14-b2-engine-tavily-cache`
- **Base:** `e14-reproducible-submission-spec` · **Stack:** `screamingface-engine`
- **Spec:** `docs/tasks/2026-08-31-OME-1045-tavily-cache-runner.md` (its scope, ordering rules,
  failure semantics and definition of done are binding) and
  `docs/spec/2026-08-31-OME-1043-tavily-retrieval-cache.md` (the route contract). E14 context:
  `prd/cache-version-capture.md` §2.2 (B2) and C15. Rules: `00-common.md`.
- Commit scope: `feat(screamingface-engine): …`. Put `Refs: OME-1045` and `Refs: OME-1307` in the body.

## Path updates (the OME-1045 task is older than the current layout)

| Task says | Today |
|---|---|
| `runner/web_tools.py` | `src/screamingface_engine/world/web_tools.py` |
| new `runner/tavily_retrieval_cache.py` | new `src/screamingface_engine/world/tavily_retrieval_cache.py` |
| `_ModelEndpoint`'s aigateway client | the aigateway `httpx.AsyncClient` the connector already uses (`world/connector.py`) |
| `_headers(profile, identity_headers)` | `world/connector.py:855` (`_headers`) |

## Files

| File | Change |
|---|---|
| `src/screamingface_engine/world/tavily_retrieval_cache.py` | new: description builder + `TavilyRetrievalCache` |
| `src/screamingface_engine/world/web_tools.py` | `WebToolRuntime.cache: TavilyRetrievalCache \| None = None`; lookup-before / fill-after in `_tavily_search` and `_tavily_extract` |
| the place that builds `WebToolRuntime` (`build_runtime`, and its caller in `connector.py`) | pass the cache built from the connector's aigateway client and headers |
| `tests/unit/test_tavily_retrieval_cache.py`, `tests/unit/test_web_tools_tavily_cache.py` | new (append-only); extend the "key never sent" check in a NEW test, not by editing `test_tavily_key_never_sent_to_aigateway` |

## Decisions (pinned)

- Description body (matches the gateway `_Description`, `apps/aigateway/src/aigateway/routes/tavily_retrieval_cache.py:65`):
  `{"provider": "tavily", "tool": "web_search" | "web_fetch", "query"?, "url"?, "search_depth"?,
  "max_results"?, "excluded_domains": [...]}`. Send exactly the arguments that shape the Tavily
  request. Check the gateway's tool names (`TOOL_WEB_SEARCH`, `TOOL_WEB_FETCH`) and use the same strings.
- `TavilyRetrievalCache.lookup(description) -> TavilyLookup` and
  `TavilyRetrievalCache.fill(description, result) -> str | None`.
  `@dataclass(frozen=True) class TavilyLookup: status: Literal["hit", "miss", "bypass"]; result: str | None;
  headers: Mapping[str, str]`. `fill` returns the gateway outcome string (`"stored"`, `"race_lost"`,
  `"not_stored"`) or `None` on any failure. **B3 will read these return values**, so keep them.
- Timeouts: lookup and fill each use a 5 s timeout (`httpx.Timeout(5.0)` per request), separate from
  Tavily's 30 s.
- Failures: lookup `except (httpx.HTTPError, ValueError)` → log + `TavilyLookup("bypass", None, {})`
  and call Tavily as today. Fill failures → log + `None`. `asyncio.CancelledError` propagates.
- Cache the string that `_tavily_search` / `_tavily_extract` return on success (post-exclusion,
  pre-truncation). Never fill `"no results"` or an extraction-failure string.
- No cache configured (`runtime.cache is None`) → byte-identical behaviour to today.

## Do not

- No in-run memo. No new config knob. Do not send the Tavily API key to the gateway.
- Do not add replay or revision logic here (that is B3).

## Verify

`python3 .claude/scripts/run_gates.py screamingface-engine --base e14-reproducible-submission-spec`

---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-06
finished: 2026-10-06
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

## Approved test changes (append-only exception)

Mock routing only, no assertion changed; orchestrator-approved under the owner's E14 authorization,
to be confirmed by the owner. Each mock gateway now answers `/v1/retrieval/tavily/cache/lookup`
(`miss`) and `/entries` (`stored`), and does not count those calls as chat calls. The remaining
routing edits are exactly these:

- `apps/screamingface-engine/tests/unit/test_aigateway_connector.py`: the `_MockAigateway` helper
  answers the cache routes and keeps those requests in a separate `cache_requests` list. This serves
  10 tests: `test_web_search_loop_executes_tavily_search_then_answers`,
  `test_web_fetch_loop_executes_tavily_extract_then_answers`,
  `test_parallel_tool_calls_both_executed_in_one_turn`,
  `test_usage_accumulates_across_round_trips_on_same_span`,
  `test_tavily_http_failure_fed_back_to_model_not_raised`,
  `test_max_iterations_exceeded_raises_resolution_error`,
  `test_extract_content_tolerates_content_none_with_tool_calls`,
  `test_tavily_search_formats_results_as_title_url_content_blocks`,
  `test_tavily_extract_reports_failed_urls_in_tool_result`,
  `test_tavily_key_never_sent_to_aigateway`. No test body is edited.
- `apps/screamingface-engine/tests/unit/test_benchmark_foundation.py`: the local `model_response`
  in `test_retrieval_policy_protects_search_results_and_direct_fetches` answers the cache routes.
- `apps/screamingface-engine/tests/unit/test_cache_policy_threading.py`: `_MockAigateway._handle`
  answers the cache routes (`test_the_tool_calling_loop_applies_the_policy_on_every_round_trip`).
- `apps/screamingface-engine/tests/unit/test_operation_accounting_failure_boundaries.py`:
  `_evaluate_rounds` uses a small function instead of a one-line lambda as the transport, so it can
  tell the cache routes from chat calls
  (`test_one_unavailable_tool_round_poisons_the_complete_operation_accounting`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the 5 planned files, plus the 4 existing test files above (approved).
- **Commits:** `git log --oneline e14-reproducible-submission-spec..HEAD`
- **Gates:** see the PR report (run without and with `--skip-append-only`).
- **Deviations:** helper names `search_description` / `fetch_description` and the private
  `_extraction` helper (accepted); the approved mock edits above.

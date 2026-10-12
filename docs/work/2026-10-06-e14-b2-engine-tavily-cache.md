---
ticket: OME-1045
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

**Owner approval:** confirmed by the owner on 2026-10-08. The append-only gate may skip these edits.

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

## Rebase onto main (2026-10-08)

- The stack was rebased onto `origin/main` `4cd063445` (87 new commits on main).
- Conflict in `world/connector.py`: main made the chat `headers` a dict with
  `x-aigw-execution-timeout-s` and `x-aigw-queue-timeout-s`. This PR builds `headers` before
  `_retrieval_request`, so main's dict now sits there. The Tavily cache still gets the same headers
  as the chat calls.
- Gates for stack `screamingface-engine` pass against `e14-b1-gateway-frozen-copy`
  (`--skip-append-only`; the approved test edits are unchanged).

## Review round 2026-10-12 (design review fixes)

- **Change (decision Q30):** the Tavily retrieval cache key includes the caller's account id.
  `apps/aigateway/src/aigateway/routes/tavily_retrieval_cache.py`: `_key_hash(body, account_id)`
  hashes `{"account", "retrieval"}` through `canonical_digest`. The `retrieval` member is the
  unchanged `tavily_retrieval_key`. Lookup and fill both pass `str(current.id)`. The two route
  handlers now name the dependency `current`, because it is used. The key is still derived
  server-side. Extra fields (`key`, `key_hash`, `account_id`) are still refused with `422`.
- **Change (docs):** `apps/aigateway/DEPLOYMENT.md`, "The Tavily Retrieval Cache" section. The
  line "Identity never enters the key" is replaced by the account-scope rule and its reason (Q30).
- **Tests:** `apps/aigateway/tests/unit/tavily_retrieval/test_tavily_retrieval_routes.py`, three
  new functions appended: `test_fill_by_one_account_is_a_miss_for_another`,
  `test_same_account_hit_is_unchanged`, `test_key_is_still_derived_server_side`. The first one
  failed before the change (the second account got the first account's fill). All 56 Tavily
  tests pass after the change.
- **Gates:**
  - `run_gates.py aigateway --base refs/e14-backup/pre-phase2-2026-10-12/OME-1434-e14-b1-gateway-frozen-copy`:
    ALL GATES GREEN.
  - `run_gates.py screamingface-engine --base refs/e14-backup/pre-phase2-2026-10-12/OME-1434-e14-b1-gateway-frozen-copy`:
    the append-only check flagged only the 4 approved files (`test_aigateway_connector.py`,
    `test_benchmark_foundation.py`, `test_cache_policy_threading.py`,
    `test_operation_accounting_failure_boundaries.py`). Rerun with `--skip-append-only`:
    ALL GATES GREEN.
- **Deviations:** none in code. The engine is unchanged in this round. Two comments outside the
  listed files still describe the old rule: the module docstring of
  `core/request_cache/tavily_retrieval.py` (identity is structurally absent), and the comment
  "it never enters the key" in `test_the_endpoints_require_an_authenticated_caller`. Both are left
  as they are. They need an owner decision.

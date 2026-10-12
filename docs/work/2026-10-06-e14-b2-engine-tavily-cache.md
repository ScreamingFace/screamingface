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
  server-side. Each extra field (`key`, `key_hash`, `account_id`) is refused with `422` on both
  routes. The test checks the error location, so it fails if a route refuses for another reason.
  The first version sent `result` to lookup, which refused that route for the wrong reason.
- **Change (docs):** `apps/aigateway/DEPLOYMENT.md`, "The Tavily Retrieval Cache" section. The
  line "Identity never enters the key" is replaced by the account-scope rule and its reason (Q30).
- **Revision bump (approved by the orchestrator):** `TAVILY_RETRIEVAL_CONTRACT_REVISION` is now
  `aigw-tavily-retrieval-2026-10a`, with the comment "Also bump when the route's account wrap (Q30)
  changes." The revision is inside every key hash, so every key changes.
  `packages/screamingface/tests/e2e/fixtures/snapshots/draco-3pass.manifest.json` line 6 holds the
  new value; no other line changed. A grep for `aigw-tavily-retrieval-2026-08a` finds no test or
  fixture that asserts it. The old value remains only in the dated spec
  `docs/spec/2026-08-31-OME-1043-tavily-retrieval-cache.md` line 146. That spec is not edited.
- **Upgrade and auth notes (DEPLOYMENT.md, approved):** a bullet on the upgrade. Every Tavily row
  written before the upgrade is a miss, and the old rows are never served. The first re-run pays
  Tavily again. A bullet on `AIGW_AUTH_MODE=disabled`: all callers share one anonymous account, so
  they share one set of rows. The "a re-run of a benchmark" sentence now says "by the same
  account".
- **Tests:** `apps/aigateway/tests/unit/tavily_retrieval/test_tavily_retrieval_routes.py`, three
  new functions appended: `test_fill_by_one_account_is_a_miss_for_another`,
  `test_same_account_hit_is_unchanged` (now logs in again and still hits), and
  `test_key_is_still_derived_server_side` (now builds the body per route and checks the error
  location). The first one failed before the change (the second account got the first account's
  fill). All 56 Tavily tests pass after the change.
- **Approved test edits (comment or docstring only, no test body changed):**
  - `apps/aigateway/tests/unit/tavily_retrieval/test_tavily_retrieval_key.py:3` (module docstring):
    "one shared row" becomes "a stored row".
  - `apps/aigateway/tests/unit/tavily_retrieval/test_tavily_retrieval_key.py:103-104` (comment in
    `test_the_key_builder_accepts_no_identity_profile_or_credential_input`): now states that the key
    builder is identity-free and that the route adds the account (Q30).
  - `apps/aigateway/tests/unit/tavily_retrieval/test_tavily_retrieval_routes.py:216` (comment in
    `test_the_endpoints_require_an_authenticated_caller`): now says identity also scopes the key to
    one account (Q30).
- **Stale comments (approved in this round):** `core/request_cache/tavily_retrieval.py` lines 3
  and 14-16 (the same file as the revision bump): "one shared row" becomes "a stored
  row", and the identity invariant now says the key is identity-free and that the route adds the
  account (Q30).
- **Gates** (both run on the working tree, which is the committed state, with `--skip-append-only`
  because the approved comment edits above are flagged by the append-only check):
  - `run_gates.py aigateway --base refs/e14-backup/pre-phase2-2026-10-12/OME-1434-e14-b1-gateway-frozen-copy --skip-append-only`:
    ALL GATES GREEN (ruff check, ruff format, pyright, no-enterprise, pytest with coverage 80).
    The append-only check without the flag flagged only `test_tavily_retrieval_key.py` and
    `test_tavily_retrieval_routes.py` (the approved comment edits).
  - `run_gates.py screamingface-engine --base refs/e14-backup/pre-phase2-2026-10-12/OME-1434-e14-b1-gateway-frozen-copy --skip-append-only`:
    ALL GATES GREEN. The append-only check without the flag flags the 4 approved files, as in the
    first round.
- **Manifest check:** no test asserts the manifest revision value. The one test that reads
  `draco-3pass.manifest.json` (`packages/screamingface/tests/e2e/test_correlation_chain.py`) is
  skipped here. It needs the e2e lane (`SCREAMINGFACE_TEST_E2E=1`) and prepared DRACO assets at
  `~/.screamingface/benchmark-assets/draco`, which are not on this machine. The manifest change is
  not verified by a run.
- **Deviations:** none in code. The engine is unchanged in this round. The two stale comments from
  the first round are now fixed (see above), so no owner decision is open for them.

# PRD: Capture the cache version of a run and bind it to the submission

**Source:** prompt / ans:Q1, ans:Q3, ans:Q4 · **Priority:** P0 (Stack B)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
**Landing:** `apps/screamingface-engine`, `apps/scoreboard`, `packages/screamingface`
**PRs:** B2 (OME-1045, a prerequisite), B3 (capture half), B4 (columns), B5 (submit half)

Uses: `prd/gateway-cache-revision.md` (the label and the header).

## 1. Summary and user story

As a researcher who submits a score, I want the submission to record which cache version produced
it, and whether every answer of the run is in the cache, so that anyone can replay that exact run
later. `[stated prompt]`

## 2. Background and constraints

- "A submission records the cache version that belongs to it. One submission, one recipe, one cache
  version." `[stated prompt]`
- The submission stores only the cache revision and a `reproducible` status. It stores no key list
  and no digest, because url4 + benchmark revision + cache revision already name the cache version.
  `[stated ans:Q3]`
- Web search must be replayable. "There`s a tavily caching mechanism already developed in the
  aigatewya … so this shouldn`t be a problem." `[stated ans:Q4]` The check showed that only the
  gateway half (OME-1044) is merged. The engine half (OME-1045) is in Backlog, so this PRD adds it
  as prerequisite PR B2. `[proposed]` (see `00-overview.md` §7, item 1)

### 2.1 Current behavior

- The engine reads `Cache-Status` or the `X-AIGW-Cache*` triple after each chat call
  `[existing apps/screamingface-engine/src/screamingface_engine/world/cache_readback.py:123]`.
  `CacheOutcome` has `status`, `reason`, `key`, `age_s` and `retried` (`cache_readback.py:93`). It
  does **not** read `X-AIGW-Cache-Write`.
- `_RunState.cache_counters` (`RunCacheCounters`) counts hits, misses and bypasses
  `[existing apps/screamingface-engine/src/screamingface_engine/runner/executor.py:351]`
  `[existing apps/screamingface-engine/src/screamingface_engine/runner/cache_counters.py:187]`.
  Its `attributes()` go into `RunSummary.cache_attributes`
  `[existing apps/screamingface-engine/src/screamingface_engine/runner/summary.py:37]`
  (`executor.py:1069`).
- The SDK reads `cache.hits` from the run summary
  `[existing packages/screamingface/src/screamingface/_engine/contract.py:214]` into `_RunOutcome`
  `[existing packages/screamingface/src/screamingface/_core/ports.py:34]` and then into
  `CandidateResult` `[existing packages/screamingface/src/screamingface/report.py:186]`.
- `CandidateResult.answer_seed` exists (`report.py:192`), but `_submission` does not send it
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:470]`. The
  benchmark revision travels in `metadata.benchmark_revision` (`leaderboards.py:499`).
- Engine web tools post straight to Tavily (`tavily_base_url = "https://api.tavily.com"`,
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:241]`;
  `[existing apps/screamingface-engine/src/screamingface_engine/world/web_tools.py:230]`
  `[existing apps/screamingface-engine/src/screamingface_engine/world/web_tools.py:262]`). No code
  calls the gateway's Tavily cache routes. OME-1045 specifies that wiring
  (`docs/tasks/2026-08-31-OME-1045-tavily-cache-runner.md`).
- Provider-native web search (for example OpenRouter `:online`) already goes through the chat
  cache (OME-777).

### 2.2 Delta

- **B2 (engine, OME-1045):** build OME-1045 as specified. Lookup before each Tavily call, fill
  after a success, and keep the Tavily credential in the engine.
- **B3 (engine):**
  - `CacheOutcome` gains `write` (`stored` | `race_lost` | `not_stored` | `None`) and `revision`
    (`str | None`). The Tavily lookup and fill outcomes feed the same counters.
  - `RunCacheCounters` adds two attributes, `cache.revision` and `cache.reproducible`, with the
    rule in §3.1 C2.
- **B4 (scoreboard):** `cache_revision`, `reproducible` and `answer_seed` on `Score` (`erd.md`
  §1), accepted on POST, fill-only on resubmit, and returned on GET.
- **B5 (SDK):** `CandidateResult` gains `cache_revision` and `reproducible` from the run summary.
  `_submission` sends `cache_revision`, `reproducible` and `answer_seed`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **C1.** Given a run whose chat calls are all hits or `stored` misses under one label, when the run
  ends, then the run summary has `cache.revision = <label>` and `cache.reproducible = "complete"`.
  `[stated ans:Q3]`
- **C2. The rule.** `reproducible = "complete"` only when **all** of these are true. Otherwise it is
  `"partial"`. `[proposed]`
  1. Each chat call is a `hit`, or a `miss` with write `stored`.
  2. Each Tavily call is a lookup `hit`, or a lookup `miss` followed by a fill with outcome
     `stored`.
  3. All calls carry the same revision label.
  4. No model or tool call failed. A failed call has no stored row, so a replay cannot answer it.
- **C3.** Given a run with web search through Tavily (after B2), when every search was a hit or was
  filled with `stored`, then the run can be `complete`. `[stated ans:Q4]`
- **C4.** Given a finished run, when the user submits it, then the payload has `cache_revision`,
  `reproducible` and `answer_seed` (when they are not NULL). The scoreboard stores them, and `GET`
  returns them. `[stated prompt]`
- **C5.** Given a run with no model call and no tool call, then `reproducible = "complete"` and
  `cache.revision` is absent. `[proposed]`

### 3.2 Error paths

- **C6.** Given any call that was a `bypass` (the user's url4 opts out, a parameter is unsupported,
  the store is down, or a `max-age` re-issue happened), then `reproducible = "partial"`.
  `[proposed]`
- **C7.** Given calls that carry two different labels (a rolling deploy), then
  `reproducible = "partial"` and `cache.revision` is absent. `[proposed]` (see gateway G18)
- **C8.** Given a miss with write `race_lost` or `not_stored`, then `reproducible = "partial"`. The
  run got an answer that the cache does not hold. `[proposed]`
- **C9.** Given a Tavily fill that returns `race_lost` or fails, or a Tavily lookup that bypasses,
  then `reproducible = "partial"`. `[proposed]`
- **C10.** Given a POST with `cache_revision` but no `reproducible`, or with
  `reproducible` not in `{complete, partial}`, or a label that does not match `^cr-[0-9a-f]{12}$`,
  then the scoreboard returns `422`. `[proposed]`

### 3.3 Derived scenarios (risk-ordered)

- **C11. An older gateway without the revision header** `[implied]` — H×M. Given responses with no
  `X-AIGW-Cache-Revision`, then `revision` is `None` for those calls. The run is `partial`, because
  it cannot name a revision to replay.
- **C12. A resubmit tries to change a set cache version** `[proposed]` — H×L. Given a same-owner
  resubmit with a different `reproducible` or `cache_revision`, then the stored values do not
  change (fill-only, I2). A NULL value is filled.
- **C13. A board that predates the fields** `[existing leaderboards.py:516]` — M×M. Given an SDK
  that sends the new fields to an old board, then the board returns `422`. The SDK omits the fields
  when they are NULL, so a run with no cache data still submits (the same pattern as
  `cache_saved_cost_archive_usd`).
- **C14. An older engine without the new attributes** `[implied]` — M×M. Given a run summary with no
  `cache.reproducible`, then `CandidateResult.reproducible` is `None` and the SDK sends neither
  field.
- **C15. The B2 Tavily rules** `[existing docs/tasks/2026-08-31-OME-1045-tavily-cache-runner.md]` —
  M×M. These hold unchanged: cache the string before truncation and after the exclusion filter;
  fill only on success; reuse the gateway HTTP client.
- **C16. Concurrency.** Two runs fill the same key at the same time. One gets `stored`, and the
  other gets `race_lost` and is `partial` (C8). This is correct: only the winner's answer is in the
  cache. `[implied]`
- **C17. Retry.** A transport retry of the same call (`retried=True`) is one call for the rule.
  Only its final outcome counts. `[proposed]`

## 4. Non-functional requirements

- **Latency** `[proposed]`: header parsing is O(1) per call. B2 adds one lookup round trip before
  each Tavily call, and one fill after each paid Tavily call. OME-1045 accepts this cost.
- **Payload** `[proposed]`: two short strings and one integer for each submission.
- **Observability** `[proposed]`: the run summary attributes show why a run is `partial`, with
  counts `cache.partial.bypass`, `cache.partial.write`, `cache.partial.revision`,
  `cache.partial.tool` and `cache.partial.error`.

## 5. Out of scope

- A key list or digest `[stated ans:Q3]`.
- Clustering, system naming, publishing (follow-ups on the epic).
- Making a `partial` run replayable. It is shown as not reproducible.

## 6. Open questions

None. (Whether B2 belongs to E14 is in `00-overview.md` §7, item 1.)

## 7. TDD plan

Build order: core-out. The engine counters (pure) come first, then the readback, then the SDK
decode, then the scoreboard columns.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `read_cache_outcome` parses today's headers into today's `CacheOutcome` | unit | `[existing cache_readback.py:123]` | H×L | passes today |
| 2 | CHAR `RunCacheCounters.attributes()` today's keys | unit | `[existing cache_counters.py:277]` | H×L | passes today |
| 3 | B2: the OME-1045 TDD list, unchanged | unit+integration | C15 | M×M | as in the OME-1045 task |
| 4 | `readback_parses_write_and_revision_headers` | unit | C2, C8 | H×M | two new optional fields |
| 5 | `run_is_complete_when_all_hits_or_stored_under_one_label` | unit | C1 | H×M | counters track the label set and the non-replayable counts |
| 6 | `run_is_partial_on_any_bypass` (table: each bypass reason) | unit | C6 | H×H | |
| 7 | `run_is_partial_on_race_lost_or_not_stored` | unit | C8 | H×M | |
| 8 | `run_is_partial_and_has_no_revision_on_two_labels` | unit | C7 | M×M | |
| 9 | `run_is_partial_when_a_call_failed` | unit | C2.4 | M×M | count failed model and tool calls |
| 10 | `tavily_lookup_hit_or_stored_fill_keeps_complete; race_lost_or_bypass_makes_partial` | unit | C3, C9 | M×M | Tavily outcomes feed the counters |
| 11 | `missing_revision_header_makes_partial` | unit | C11 | H×M | |
| 12 | `retried_call_counts_once` | unit | C17 | L×M | |
| 13 | `empty_run_is_complete_without_revision` | unit | C5 | L×L | |
| 14 | SDK `contract_decodes_revision_and_reproducible_into_candidate_result` | unit | C1, C14 | H×M | `_RunOutcome` + `CandidateResult` fields |
| 15 | SDK `submit_sends_cache_version_and_answer_seed_when_present_else_omits` | unit | C4, C13 | M×M | `_submission` |
| 16 | scoreboard `post_stores_and_get_returns_cache_version_fields` | integration | C4 | M×M | migration `0020` (columns) |
| 17 | scoreboard `post_rejects_bad_label_or_status_pairing` | unit | C10 | M×M | validator |
| 18 | scoreboard `resubmit_fills_null_cache_version_but_never_replaces` | integration | C12 | H×L | add to `_replay_updates` as fill-only |

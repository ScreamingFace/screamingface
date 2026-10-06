# PRD: Reproduce a submission and record the reproduction

**Source:** prompt / ans:Q1, ans:Q2, ans:Q6, ans:Q8, ans:Q9 · **Priority:** P0 (Stack B, the user-facing end)
**Lifecycle:** planned (new flow on existing seams)
**Owner:** unassigned
**Landing:** `apps/screamingface-engine`, `apps/scoreboard`, `packages/screamingface`
**PRs:** B4 (replay half), B5 (reproductions), B6 (`sf.reproduce`)

Uses: `prd/gateway-cache-revision.md` (the controls), `prd/cache-version-capture.md` (the stored
cache version).

## 1. Summary and user story

As someone who reads a leaderboard result, I want to rerun exactly that submission from its cache
version, at no provider cost, and record that it reproduced, so that I can trust and cite it.
`[stated prompt]`

## 2. Background and constraints

- "Rerunning that exact recipe can use that cache version." `[stated prompt]`
- "You can pin a run to a specific recipe. You can also pin by date." `[stated prompt]` Here, a pin
  is a choice of submission. The url4 is the recipe pin. The list of scores (`submitted_at`) is the
  date pin. `[stated ans:Q3]`
- Keep `only-if-cached`. `[stated ans:Q2]` Old revisions stay replayable. `[stated ans:Q1]`
- Record a reproduction: "Record a reproduction" `[stated ans:Q6]`, "Only exact replays"
  `[stated ans:Q8]`, "Verified identity, multiple times (no limit of cap)" `[stated ans:Q9]`.

### 2.1 Current behavior

- The engine reads `Cache-Control`, `X-Profile`, `X-Answer-Seed` and `traceparent` into a
  `RequestScope` `[existing apps/screamingface-engine/src/screamingface_engine/request_scope.py:54]`
  `[existing apps/screamingface-engine/src/screamingface_engine/request_scope.py:147]`.
- The connector adds `policy_to_body_field(cache)` to each chat body. It re-issues without the
  cache when a `max-age` bound refuses a hit
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:794]`
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:806]`.
- A non-2xx gateway response becomes `ResolutionError`, which fails the case
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1097]`.
- The SDK sends `X-Answer-Seed` to the engine
  `[existing packages/screamingface/src/screamingface/_engine/transport.py:1197]`.
  `get_score(score_id)` returns a `LeaderboardScore`
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:114]`
  `[existing packages/screamingface/src/screamingface/leaderboard.py:118]`.
- The documented way to reproduce today is a fresh paid run, `sf.evaluate(score.url4)`
  `[existing public-docs/src/pages/sf-client/guides/LeaderboardsPage.vue:46]`.
- Failures show as result fields (`CandidateResult.failures`, `CaseResult.failures`), not as
  exceptions `[existing packages/screamingface/src/screamingface/report.py:205]`.

### 2.2 Delta

- **B4 (engine, replay half):**
  - A new inbound header `X-Cache-Replay: <label>` sets `RequestScope.replay_revision`.
  - In replay mode, each chat body gets `cache: {"only-if-cached": true, "cache-revision": <label>}`
    in place of the policy field, and the connector never re-issues.
  - Each Tavily lookup sends `cache_revision`. A lookup miss or bypass never calls Tavily.
  - A gateway `504` with `cache_miss` or `cache_bypass`, or a Tavily replay miss, fails the case
    with the failure code `replay_cache_miss`.
- **B5 (scoreboard):**
  - The `score_reproductions` table (`erd.md` §3).
  - `POST /v1/scores/{id}/reproductions`.
  - `reproduction_count` and `last_reproduced_at` on `ScoreSchema`, and a count on the portal spec
    page.
- **B6 (SDK):** `Client.reproduce(score, *, record=True) -> Reproduction`, the same on
  `AsyncClient`, and the module-level `sf.reproduce`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **R1.** Given a score with `reproducible = "complete"` and a cache revision L, when a user calls
  `sf.reproduce(score)`, then the SDK runs `evaluate(score.url4, answer_seed=score.answer_seed)`
  with the header `X-Cache-Replay: L`. The score's url4 is a complete URL4: it already holds the
  benchmark and the case limit, and `evaluate` refuses `benchmark=` and `limit=` for it
  `[existing packages/screamingface/src/screamingface/client.py:691]`. The answer seed is not in the
  url4, so it comes from the score (`erd.md` §1). Every call is served from the cache. The run costs
  no provider spend. `[stated prompt]` `[stated ans:Q2]`
- **R2.** Given that run, when no case failed with `replay_cache_miss`, the score and the case
  count equal the stored ones, and the benchmark revision equals `score.benchmark_revision`, then
  `Reproduction.outcome = "exact"`. `[stated ans:Q8]`
- **R3.** Given an exact replay and `record=True` (the default), then the SDK posts
  `{run_id, score, total_questions, cache_revision, client}` to
  `POST /v1/scores/{id}/reproductions`. The board stores one row, and `Reproduction.recorded` is
  `True`. `[stated ans:Q6]`
- **R4.** Given recorded reproductions, when anyone reads the score, then `reproduction_count` and
  `last_reproduced_at` show them. The portal spec page shows "Reproduced N times". `[proposed]`
- **R5.** Given a score stored under an older label L1, and a gateway that now runs L2, when the
  user reproduces it, then the replay uses L1 and is exact. `[stated ans:Q1]`
- **R6.** Given the same identity, when it reproduces the same score again with a new run, then a
  second row is stored, with no cap. `[stated ans:Q9]`

### 3.2 Error paths

- **R7.** Given a score with `reproducible` of `partial` or NULL, then `sf.reproduce` returns
  `outcome = "not_reproducible"` with `reason = "partial"` or `"unknown"`, and it starts no run.
  `[stated ans:Q8]`
- **R8.** Given a replay where some calls miss, then those cases fail with `replay_cache_miss`.
  `outcome = "failed"`, `reason = "cache_miss"` and `missed_cases` lists their ids. Nothing is
  recorded. `[stated ans:Q2]` `[stated ans:Q8]`
- **R9.** Given a replay whose benchmark revision differs from `score.benchmark_revision`, then
  `outcome = "failed"` and `reason = "benchmark_revision_changed"`. `[implied]`
- **R10.** Given a replay with no misses but a different score or case count, then
  `outcome = "failed"` and `reason = "score_differs"`. `[implied]`
- **R11.** Given a label that the gateway does not know (the gateway is older than the score), or
  a gateway without `GET /v1/cache/revisions`, then the engine fails the run before the first chat
  call. `outcome = "failed"` and `reason = "unknown_cache_revision"`. `[implied]` (`contracts.md` K10)
- **R12.** Given `POST …/reproductions` with no identity, then it returns `401`. Given an untrusted
  peer, then it returns `403`. This is the same `VerifiedIdentity` dependency as PATCH.
  `[stated ans:Q9]`
- **R13.** Given `POST …/reproductions` for a score whose `reproducible` is not `complete`, then it
  returns `409` with code `not_reproducible`. `[stated ans:Q8]`
- **R14.** Given a body whose `score`, `total_questions` or `cache_revision` differs from the stored
  score, then it returns `422` with code `not_exact`. `[stated ans:Q8]`
- **R15.** Given a private-board score and a caller who is not the owner, then it returns `404`.
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:334]`
- **R16.** Given an exact replay and a failed record POST (network error or 5xx), then
  `sf.reproduce` still returns `outcome = "exact"`, with `recorded = False` and `record_error`
  set. It does not raise. `[proposed]`

### 3.3 Derived scenarios (risk-ordered)

- **R17. A replay must never pay a provider** `[stated ans:Q2]` — Impact H × Likelihood M. Given
  replay mode, then no chat body omits `only-if-cached`, the `max-age` re-issue is off, and Tavily
  is never called on a lookup miss or bypass.
- **R18. Retry of the same record** `[proposed]` — M×M. Given the same `run_id` posted twice, then
  the second returns `200` with the first row. The unique `(score_id, run_id)` index stops a double
  count. A new `run_id` returns `201`.
- **R19. A user's url4 opts out of the cache** `[implied]` — M×L. Such a run is `partial` at
  capture (`prd/cache-version-capture.md` C6), so R7 stops it before any run.
- **R20. The case set** `[existing packages/screamingface/src/screamingface/client.py:691]` — M×L.
  The complete url4 fixes the benchmark and the limit, so the replay loads the same cases. TDD #1
  pins that two runs of one complete url4 load the same case ids.
- **R21. Self-reported trust** `[implied]` — M×M. The board cannot prove that a replay ran, which
  is also true for scores today (`verified_by_screamingface` is a placeholder,
  `[existing apps/scoreboard/src/scoreboard/scores/models/score.py:77]`). It checks only that the
  numbers and the revision match. A record names its verified identity, so readers can weigh it.
- **R24. An older engine ignores the replay header** `[implied]` — H×L. The engine acknowledges
  replay mode in the run-start response. When the ack is missing, the SDK cancels the run and
  returns `failed` / `replay_unsupported`. No case runs as a normal, paid call (`contracts.md` K3).
- **R22. Concurrency.** Two records at the same time each insert one row. The count is derived on
  read, so there is no lost update. `[implied]`
- **R23. Empty run** (no cacheable calls, `cache_revision` NULL) `[proposed]` — L×L. Replay
  sends no `X-Cache-Replay`. It is exact when the score matches.

## 4. Non-functional requirements

- **Cost** `[stated ans:Q2]`: a replay has zero provider spend by construction. It still uses
  engine compute.
- **Latency** `[proposed]`: a replay is at least as fast as a fully cached normal run. The record
  POST is one insert, under 50 ms p95.
- **Abuse** `[stated ans:Q9]`: there is no cap. Each row needs a verified identity and a distinct
  `run_id`. Revisit if one identity writes more than 1,000 rows for one score in one day.
- **Observability** `[proposed]`: the engine run summary counts `replay_cache_miss` cases. The board
  logs each record with the score id and the status. Emails are not logged.

## 5. Out of scope

- Recording failed replays `[stated ans:Q8]`.
- Clustering a reproduction as "another reported result", system naming, publishing (epic
  follow-ups).
- Replaying a `partial` score in part.
- A public `evaluate(..., cache_replay=…)` option. Replay is reached only through `reproduce`.
  `[proposed]`

## 6. Open questions

None.

## 7. TDD plan

Build order: outside-in from the SDK's `Reproduction` outcome table. Engine replay and the board
endpoint are pinned by their own integration tests first, because R17 is the top risk.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR two runs of one complete url4 load the same case ids | integration | R20 | M×L | passes today, by design |
| 2 | engine `replay_header_sets_only_if_cached_and_revision_on_every_chat_body` | unit | R1, R17 | H×M | `request_scope_from_headers` + connector (B4) |
| 3 | engine `replay_mode_never_reissues_on_max_age` | unit | R17 | H×M | skip `requires_revalidation` in replay mode |
| 4 | engine `replay_tavily_miss_or_bypass_never_calls_tavily_and_fails_case` | unit | R17, R8 | H×M | raise `replay_cache_miss` before the Tavily POST |
| 5 | engine `gateway_504_cache_miss_fails_case_with_replay_cache_miss` | unit | R8 | H×M | map in `_raise_for_status` |
| 6 | engine `replay_checks_revisions_read_and_fails_run_before_first_call` (404, or label not known) | unit | R11, R17 | H×M | call K10 once at replay start |
| 7 | board `record_without_identity_401_untrusted_403` | integration | R12 | H×M | `VerifiedIdentity` (B5) |
| 8 | board `record_on_partial_or_null_score_is_409` | integration | R13 | H×M | |
| 9 | board `record_with_mismatched_numbers_or_revision_is_422` | integration | R14 | H×M | |
| 10 | board `record_private_score_by_non_owner_is_404` | integration | R15 | H×M | |
| 11 | board `record_same_run_twice_returns_first_row_200` | integration | R18 | M×M | unique `(score_id, run_id)` |
| 12 | board `same_identity_new_run_adds_row_no_cap` | integration | R6 | M×M | no per-identity limit |
| 13 | board `score_read_shows_count_and_last_time` | integration | R4 | M×M | aggregate on read |
| 14 | portal `spec page shows reproduced count` | unit (JS) | R4 | L×M | |
| 15 | SDK `partial_or_null_score_is_not_reproducible_without_running` | unit | R7 | H×M | check before any transport call (B6) |
| 16 | SDK `reproduce_sends_url4_seed_and_replay_header_and_no_benchmark_or_limit` | unit | R1 | H×M | transport header like `_answer_seed_header` |
| 17 | SDK `outcome_table` (exact / cache_miss / benchmark_revision_changed / score_differs / unknown_cache_revision / replay_unsupported) | unit | R2, R8–R11 | H×M | one pure function over the result |
| 18 | SDK `exact_replay_records_once_and_sets_recorded` | unit | R3 | M×M | POST via MockTransport |
| 19 | SDK `record_failure_keeps_exact_and_sets_record_error` | unit | R16 | M×L | catch, do not raise |
| 20 | SDK `old_label_is_sent_verbatim` | unit | R5 | M×M | use `score.cache_revision` as is |
| 21 | SDK `empty_run_score_replays_without_header` | unit | R23 | L×L | |
| 22 | e2e `submit_then_reproduce_is_exact_and_recorded` (local stack) | e2e | R1–R3 | H×M | the one spine test |
| 23 | engine `start_response_echoes_replay_header_before_any_case_runs`; SDK `missing_ack_cancels_run` | unit | R24 | H×L | ack in the start response |

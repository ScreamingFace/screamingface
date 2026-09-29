# PRD: Submit a result — freeze its cache version, name it, cluster it

**Source:** ticket §1–2 · Irina answers 1 and 3 · ans:Q1, Q3, Q8, Q11, Q14, Q15 · **Priority:** P0
**Lifecycle:** existing (characterize, then the delta)
**Owner:** unassigned

## 1. Summary and user story

As a researcher, I want each result I submit to record the exact cache that produced it,
under a stable system name, so that others can find it, rerun it and cite it. A rerun of the
same system shows as another reported result under the first claim. It does not show as a
competing row.

## 2. Background and constraints

- "A submission records the cache version that belongs to it. One submission, one recipe, one
  cache version." `[stated prompt]`
- "Bruno submitting the same url4 will lead to 'another reported result' clustered under
  Ana's result, but will not add a new row. This is useful in case the underlying models
  change - to track changes, but the claim belongs to Ana." `[stated prompt]` (Irina answer 1)
- The original result ranks. Later results show as history `[stated ans:Q11]`.
- The system name and revision rules come from `prd/system-registry.md` (`ans:Q8`, `Q14`, `Q15`).
- The freeze and the receipt come from `prd/cache-version-store.md`.
- Entities: `Score` (the head), `ReportedResult` (`erd.md` §2.1–2.2). The cluster key is in
  `erd.md` §2.4.

### 2.1 Current behavior

- `POST /v1/scores` creates one `Score` row per distinct `content_hash`. The hash covers
  benchmark, revision, `spec_id`, url4, score, question count and providers. It covers
  `submitted_by` only on private boards
  `[existing apps/scoreboard/src/scoreboard/scores/store.py:335]`.
- The same `Idempotency-Key` (the `run_id`), or the same content hash, returns the existing
  row with `200`. A new row returns `201`
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:177-285]`.
- So the same url4 with a different score makes a **second, unrelated row**. The leaderboard
  then keeps the best row per `(spec_id, benchmark_revision)`
  `[existing apps/scoreboard/src/scoreboard/scores/store.py:592]`.
- A private board refuses a write without a verified submitter
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:225]`.
- The report carries `trace_id`, `run_id`, `answer_seed`, `models`, the benchmark revision and
  the cost, but nothing about which cache served the run beyond `cache_saved_cost_usd`
  `[existing packages/screamingface/src/screamingface/report.py:184-215]`.
- The SDK sends `Idempotency-Key: run_id`
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:106]`.

**Delta.**
1. The SDK freezes the run's cache version through the engine (new engine proxy route) and
   gets a signed receipt.
2. The SDK submits with the receipt, an optional `paper_url` (`prd/edit-metadata.md`) and an
   optional `revision_of`.
3. The scoreboard verifies the receipt and resolves the system name (public boards). It then
   either creates a head plus its original `ReportedResult`, or appends a `ReportedResult`
   to an existing head.
4. `GET /v1/scores/{id}/results` lists a head's reported results. The portal shows the count.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**SC-H1** `[stated prompt]` — the first submit of a system.
Given Ana ran candidate C (trace T) on public board B, revision R,
when Ana calls `client.leaderboards.submit(result, authors=[...])`,
then:
1. the SDK calls the engine `POST /v1/cache-versions {"trace_id": T}` and gets a receipt;
2. the SDK calls `POST /v1/scores` with the report payload plus `cache_version_receipt`;
3. the scoreboard creates head H and `ReportedResult(is_original=true)` with
   `cache_version_id` and the digest from the receipt;
4. the response is `201` with the head, the reported result and its cache version summary.

**SC-H2** `[stated prompt]` — another reported result.
Given head H exists for `(B, R, system revision S)`, owned by Ana,
when Bruno submits a run of the same candidate (same fingerprint) on B, revision R,
then no new head is created. A `ReportedResult(is_original=false, reporter=bruno)` is
appended to H with Bruno's score, cost and cache version. The response is `201` with
`reported_result.is_original=false` and the notice `{"code": "clustered_under", "score_id": H}`.

**SC-H3** `[stated ans:Q11]` — the original still ranks.
Given SC-H2, where Bruno's score differs from Ana's,
then the leaderboard row of H still shows Ana's score and cost. H's ranked columns do not
change (I-S2).

**SC-H4** `[stated prompt]` — model drift is visible.
Then `GET /v1/scores/{H}/results` lists both results, newest first, with each result's
`models`, score, `submitted_at`, reporter and cache version id. The portal shows "2 reported
results" on H's row, with a link to the list.

**SC-H5** `[stated ans:Q14]` — a revision submit.
When Kevin submits a new fingerprint with `revision_of="kevins-best"`,
then a new head is created for the new system revision, with `spec_id="kevins-best"`. The
best-per-`(spec_id, revision)` rule ranks the better revision, as today.

**SC-H6** `[stated ans:Q15]` — a name notice.
When Bruno sends name `bruno-opus` for a system already named `opus-5.5`,
then the result clusters under `opus-5.5`, and the response carries the notice
`system_already_named` (SR-H3).

### 3.2 Error paths

**SC-E1** `[proposed]` — the freeze fails, so the submit proceeds without a version.
When the engine or the gateway is down, times out (60 s), or returns `404 trace_not_captured`
or `413 cache_version_too_large`,
then the SDK still submits, with no receipt. The row has all cache version columns `NULL`
(I-R1). The SDK returns the score with the local warning
`cache_version_unavailable: <reason>` and logs it. Why: a paid run must never be lost to an
optional artifact.

**SC-E2** `[proposed — gap §security]` — the receipt is not valid.
When the receipt fails the signature check, has an unknown `kid`, or is malformed,
then the response is `422 invalid_cache_version_receipt`, and nothing is written. The SDK
does not retry this automatically. It raises, so the bug surfaces.

**SC-E3** `[proposed]` — the receipt does not belong to the caller or the run.
When the receipt `sub` is not the verified submitter, or the receipt `tid` is not the
submitted `trace_id`,
then the response is `403 cache_version_not_yours`, and nothing is written.

**SC-E4** `[proposed]` — the version is already bound.
When a receipt's `vid` is already bound to a different `ReportedResult` (a different
`run_id`), then the response is `409 cache_version_already_bound`. The same `run_id` is the
idempotent replay (SC-D1).

**SC-E5** — registry errors pass through: `403 not_system_owner`, `404 system_not_found`,
`409 system_name_taken`, `422 invalid_system_name` (`prd/system-registry.md` SR-E1 to SR-E4).
The SDK keeps the report and the receipt, so a resubmit with a fixed name needs no rerun and
no new freeze (the freeze is idempotent, CV-D3).

**SC-E6** `[existing apps/scoreboard/src/scoreboard/routes/scores.py:225]` — a private board
without a verified submitter is still refused.

### 3.3 Derived scenarios (risk order)

**SC-D1 — a retried submit never makes two rows** `[proposed — gap §per-flow/repeat]` · H×H
When the SDK resends the same submit (same `run_id`) after a lost response,
then the response is `200` with the same head and the same reported result. Unique
`ReportedResult.run_id`. This replaces the head-level content-hash replay for new rows.

**SC-D2 — two reporters race on a new cluster** `[proposed — gap §concurrency]` · H×M
When Ana and Bruno submit the same new system on the same board at the same time,
then exactly one head exists (partial unique index I-S1). The loser retries once in a new
transaction and becomes a reported result under the winner's head. The claim belongs to
whoever committed first.

**SC-D3 — a legacy row with the same url4** `[proposed]` · H×M
Given a legacy head (from before E14) with the same url4 on the same board and revision, whose
fingerprint the `backfill-systems` command linked,
when a new submit of that system arrives,
then it clusters under the legacy head. If the legacy head is not yet linked and the new head
would collide on `content_hash`, then the submit links the legacy head to the system revision
in the same transaction and clusters under it.

**SC-D4 — the report and the scoreboard disagree on the benchmark revision** · M×M
Today's revision rules stay as they are
`[existing apps/scoreboard/src/scoreboard/scores/store.py:139]`. The cluster key uses the
resolved revision, never the client's metadata value.

**SC-D5 — a partial cache version** `[stated ans:Q13]` · M×M
When the receipt says `cov=partial` (missing calls, CV-E2), then the result is stored with
`cache_coverage_status=partial`, and the results list shows "partial cache (N of M calls)".

**SC-D6 — a run with no trace** `[proposed]` · M×L
When the report has `trace_id = None`, then the SDK skips the freeze and submits with no
version, with the warning `cache_version_unavailable: no_trace` (CV-D5).

**SC-D7 — a submit of a pinned replay run** `[stated prompt]` · H×M
When a run that was pinned to a version (`prd/replay-pinned-run.md`) is submitted,
then the `ReportedResult` stores `replayed_from_result_id`, `replay_hits`, `replay_misses` and
`pinned_baseline_result_id` from the report. The results list labels it "replay of <result>
(hits/total)", so a pure cache replay is never shown as an independent reproduction.

**SC-D8 — the original result's publish state** `[implied]` · M×M
A new `ReportedResult` with a cache version gets a `CacheVersionPublication` row in state
`private` (`erd.md` §2.6). A result with no version gets no row.

**SC-D9 — a private board** `[proposed]` · H×L
On a private board, the cluster key is `(benchmark, revision, submitter, fingerprint)`. No
registry write happens (SR-D8). The results list and the head are readable by the owner only.

**SC-D10 — the results list pages** `[proposed — gap §performance]` · M×M
`GET /v1/scores/{id}/results` uses cursor paging (default 50, maximum 200), ordered by
`(submitted_at DESC, id DESC)`. A head with 10,000 results answers in ≤ 200 ms p99.

**Not applicable:** a cancel between the freeze and the submit leaves an unbound version.
That is accepted and costs little (`erd.md` §3.6).

## 4. Non-functional requirements

- The submit p99 grows by ≤ 150 ms for a verified receipt (EdDSA verify ≤ 1 ms, plus the
  registry at ≤ 20 ms, plus the cluster lookup) `[proposed]`. The freeze time (≤ 10 s) is on
  the SDK side, before the submit.
- Observability `[proposed]`:
  - `scoreboard_submits_total{kind=new_head|reported_result|replay_idempotent}`
  - `scoreboard_receipt_rejections_total{reason}`
  - SDK log `cache_version_unavailable` with a reason
- Security: the receipt is the only way a `cache_version_id` enters the scoreboard. The
  scoreboard trusts no client field about versions.

## 5. Out of scope

- Merging legacy duplicate rows into clusters (`erd.md` §6, point 4).
- Attaching a cache version after the submit.
- Per-question sample views (OME-1360), a cross-benchmark Pareto (OME-1367) and
  reproducibility tooling (OME-1341) `[stated ans:Q12]`.

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: characterization, then the idempotency and integrity core, then the trust boundary
(the receipt), then clustering, then the SDK orchestration, then the portal. Outside-in from
the route.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| SC-1 | CHAR `same_run_id_returns_existing_row_200` | integration | [existing routes/scores.py:177] | H×L | none |
| SC-2 | CHAR `private_board_refuses_unverified_write` | integration | [existing routes/scores.py:225] | H×L | none |
| SC-3 | `retried_submit_same_run_id_one_reported_result` | integration | [proposed] SC-D1 | H×H | unique `run_id` |
| SC-4 | `receipt_bad_signature_422_nothing_written` | integration | [proposed] SC-E2 | H×M | verifier port with a kid map |
| SC-5 | `receipt_sub_or_tid_mismatch_403` | integration | [proposed] SC-E3 | H×M | compare to the verified submitter and `trace_id` |
| SC-6 | `receipt_vid_bound_to_other_run_409` | integration | [proposed] SC-E4 | H×L | unique `cache_version_id` |
| SC-7 | `first_submit_creates_head_and_original_result_with_version` | integration | [stated prompt] SC-H1 | H×H | one transaction |
| SC-8 | `same_system_second_reporter_appends_result_no_new_head` | integration | [stated prompt] SC-H2 | H×H | lookup by cluster key |
| SC-9 | `later_result_never_changes_head_ranked_columns` | integration | [stated ans:Q11] SC-H3 | H×H | no update of the head |
| SC-10 | `concurrent_new_cluster_one_head_loser_becomes_result` | integration | [proposed] SC-D2 | H×M | catch the unique violation, retry once |
| SC-11 | `legacy_head_same_url4_links_and_clusters` | integration | [proposed] SC-D3 | H×M | content-hash collision handler |
| SC-12 | `cluster_key_uses_resolved_revision_not_client_metadata` | unit | [existing store.py:139] SC-D4 | M×M | |
| SC-13 | `private_board_cluster_per_submitter_no_registry` | integration | [proposed] SC-D9 | H×L | |
| SC-14 | `replay_run_stores_provenance_and_label` | integration | [stated prompt] SC-D7 | H×M | report fields → columns |
| SC-15 | `partial_receipt_stored_as_partial` | unit | [stated ans:Q13] SC-D5 | M×M | |
| SC-16 | `new_versioned_result_gets_private_publication_row` | unit | [implied] SC-D8 | M×M | |
| SC-17 | `results_list_cursor_paged_newest_first` | integration | [proposed] SC-D10 | M×M | index `reported_result (head_id, submitted_at, id)` |
| SC-18 | `sdk_submit_freezes_then_submits_with_receipt` | unit (`httpx.MockTransport`) | [stated prompt] SC-H1 | H×H | the SDK orchestration |
| SC-19 | `sdk_freeze_failure_submits_without_version_and_warns` (table: timeout, 404, 413, 5xx, no trace) | unit | [proposed] SC-E1 SC-D6 | H×M | catch, warn, continue |
| SC-20 | `sdk_keeps_receipt_for_resubmit_after_name_error` | unit | [proposed] SC-E5 | M×M | cache the receipt on the result object |
| SC-21 | `engine_cache_versions_route_proxies_with_caller_identity` | integration | [proposed] contracts C2 | H×M | reuse the `connections/aigateway.py` pattern |
| SC-22 | `portal_shows_reported_results_count_and_link` | unit (portal) | [stated prompt] SC-H4 | M×M | |
| SC-23 | E2E `two_users_same_system_one_row_two_results_original_ranks` | E2E | [stated prompt] SC-H2 SC-H3 | H×H | the spine (local `screamingface up`) |

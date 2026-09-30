# PRD: Rerun pinned to a cache version — by submission, by name, by date

**Source:** ticket §2 · ans:Q4, Q6, Q7, Q10, Q13, Q14 · **Priority:** P0
**Lifecycle:** planned. It changes the existing SDK `evaluate`, the engine request scope and
the gateway chat path.
**Owner:** unassigned

## 1. Summary and user story

As a researcher, I want to rerun a published recipe against the exact cache version of a
submission, or against the version of a system as it was on a date, so that I can reproduce
the result, or compare my newer recipe with the earlier one.

## 2. Background and constraints

- "Rerunning that exact recipe can use that cache version." `[stated prompt]`
- "If more than one cache version exists, the run API can name the one you want."
  `[stated prompt]`
- "You can pin a run to a specific recipe. You can also pin by date, so a newer run of the same
  work under a new recipe can be compared with the earlier one, and the difference can be
  looked up." `[stated prompt]`
- Pin-by-date resolves to the newest cache version of a system name at or before time T
  `[stated ans:Q7]`. A name spans revisions `[stated ans:Q14]`.
- Anyone can replay a public submission's version. Only the owner can replay a private one
  `[stated ans:Q4]`. Private-board and gated-benchmark versions are owner-only
  `[stated ans:Q6]`.
- A miss falls through to the live provider, and the run is marked partial `[stated ans:Q13]`.
- A takedown is admin-only `[stated ans:Q10]`.
- Components used: `prd/system-registry.md` (pin resolution) and `prd/cache-version-store.md`
  (lookup, grant verification).

### 2.1 Current behavior

- `client.evaluate(candidates, *, benchmark, limit, on_event, progress, answer_seed)` has no
  replay option `[existing packages/screamingface/src/screamingface/client.py:205-216]`.
- The engine binds a per-run `RequestScope` (identity headers, profile, answer seed, cache
  policy) from the request headers
  `[existing apps/screamingface-engine/src/screamingface_engine/request_scope.py:80-172]`.
  The worker child rebuilds it from the job environment
  `[existing apps/screamingface-engine/src/screamingface_engine/runner/main.py:102]`.
- The connector writes the gateway-owned headers last (`X-Profile`, `traceparent`)
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1048-1078]`.
- The only cache control the engine sends is the opt-out `{"cache": {"use-cache": false}}`
  `[existing apps/screamingface-engine/src/screamingface_engine/world/cache.py:30-56]`.
- The engine counts hits, misses and bypasses per run from the response headers
  `[existing apps/screamingface-engine/src/screamingface_engine/runner/cache_counters.py:187-253]`.
  The report keeps only `cache_saved_cost_usd`.

**Delta.**
- SDK `evaluate(..., replay=<pin>)`.
- Scoreboard `POST /v1/replay-grants`.
- An opaque grant carried SDK → engine → gateway.
- Gateway version lookup (CV-H4, CV-H5).
- Engine counters for version hits and misses.
- A `replay` block in the report.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

Pin forms `[proposed]`:
- `result:<uuid>`: one reported result.
- `score:<uuid>`: a head, meaning its original result.
- `<name>`: the latest revision, meaning its head's original result on the run's benchmark.
- `<name>@r<N>`: revision N, resolved the same way.
- `<name>@<ISO-8601>`: pin-by-date.

**RP-H1** `[stated prompt]` — replay a submission.
Given Ana's public, redistributable result X has version V,
when Bruno calls `client.evaluate(candidate, benchmark=B, replay="result:X")`,
then:
1. the SDK calls `POST /v1/replay-grants {"pin": "result:X", "benchmark_id": B}` and gets a
   grant for V;
2. the SDK sends the grant to the engine with the run;
3. each gateway call that V holds is served from V (no provider cost);
4. the report has `replay = {result_id: X, cache_version_id: V, hits: 420, misses: 0,
   coverage: "complete"}`.

**RP-H2** `[stated ans:Q7]` — pin by date.
Given `kevins-best` has results on B with versions from 2026-08-10 (r1) and 2026-09-05 (r2),
when a user runs with `replay="kevins-best@2026-09-01"`,
then the grant names the 2026-08-10 version: the newest accessible one at or before T. The
report's `pinned_baseline_result_id` is that result. Pin-by-date looks across all revisions of
the name `[stated ans:Q14]`.

**RP-H3** `[stated prompt]` — compare a new recipe with the old one.
Given Kevin runs a changed recipe (fingerprint F3) with `replay="kevins-best@2026-09-01"`,
then the calls that the changed recipe shares with the old one are version hits. The new calls
are misses that go to the live provider. The report shows `hits` and `misses`, and the
baseline result id, so the difference can be looked up through `GET /v1/scores/{id}/results`.
The E2E test for this scenario (RP-22) is dropped (owner, 2026-09-30, Q30): no paid run is used as a test; covered by RP-6, RP-7, CV-17, RP-13, RP-21.

**RP-H4** `[stated ans:Q4]` — the owner replays a private version.
Given Ana's result on a private board has version V,
when Ana runs with `replay="result:<id>"`,
then she gets a grant. Anyone else gets `404` (no existence leak).

**RP-H5** `[stated ans:Q13]` — the partial report.
When a replay has 412 hits and 8 misses, then the report shows `coverage: "partial"`, the
8 misses cost live provider money, and the run finishes normally.

### 3.2 Error paths

**RP-E1** `[proposed]` — the pin does not resolve.
When the name, id or date matches nothing accessible (unknown name, no versioned result at or
before T, a private result of another user), then `POST /v1/replay-grants` returns
`404 replay_pin_not_found`. The SDK raises **before** the run starts, so nothing is spent.

**RP-E2** `[stated ans:Q6]` — a gated or non-redistributable public board.
When a non-owner pins a result on a public board with `redistributable=false`,
then the response is `404 replay_pin_not_found`. For the owner, the grant is issued.

**RP-E3** `[stated ans:Q10]` — a withdrawn version.
When a non-owner pins a result whose publication is `withdrawn`, then the response is
`410 cache_version_withdrawn`, with no content. The owner can still replay it `[proposed]`.

**RP-E4** `[proposed]` — a benchmark mismatch.
When `result:<id>` or `score:<id>` belongs to benchmark B2 but the run is on B,
then the response is `422 replay_benchmark_mismatch`. A version from another benchmark
would give almost zero hits and a misleading report.

**RP-E5** `[proposed]` — the scoreboard is down or times out (10 s).
The SDK raises `ReplayUnavailable` before the run starts. It never falls back to a plain run
silently, because the user asked for a replay.

**RP-E6** `[proposed]` — the gateway rejects the grant mid-run (for example, a key rotation
mistake, or a grant that expires during a long run, RP-D3).
Each affected call fails with `403 replay_grant_invalid` (CV-E4). The run fails with a typed
error that names the grant reason. It does not silently become a live run.

**RP-E7** `[proposed]` — several candidates with one pin.
When `evaluate` gets more than one candidate and a `replay` pin, the SDK raises `ValueError`
in v1. A version belongs to one recipe run.

**RP-E8** `[proposed]` — a malformed pin (for example, a bad date or `@r0`).
The SDK raises `ValueError` before any call. The scoreboard also returns
`422 invalid_replay_pin`.

### 3.3 Derived scenarios (risk order)

**RP-D1 — the grant cannot be reused by another user** `[proposed — gap §security]` · H×M
Given Bruno got a grant for a public version,
when Carol sends Bruno's grant with her own identity (an authenticated mode),
then the gateway rejects it with `subject` (CV-E4). A leaked grant does not widen access to a
private version.

**RP-D2 — the engine never parses the grant** `[proposed — gap §dependency]` · M×M
The engine treats the grant as an opaque string of at most 2 KB. It carries it in
`RequestScope.replay_grant` and in the job environment, and writes it as the gateway-owned
header `X-AIGW-Cache-Replay` **last**. This follows the existing ordering invariant
`[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1051]`. A
caller cannot inject that header through identity headers.

**RP-D3 — the grant lives 12 h, with no refresh** `[stated ans:Q21]` · H×M
The grant `exp` is `iat + 43,200 s` (12 h). This is **not** always longer than a run: the
engine job deadline is 57,600 s, and the queue wait can add up to 57,600 s more (A3, checked
false and accepted, D4). A replay grant that expires during a run fails that run with the
typed error of RP-E6 (`403 replay_grant_invalid`, `reason: expired`; RP-14). The run does not
become a live run. There is no grant refresh. Cost: a takedown blocks new grants at once, but
an issued grant can work for up to 12 h. Change when: long replays fail on expiry often (then
raise the TTL or add a refresh), or a takedown must take effect within minutes (then add a
revocation list that the gateway pulls).

**RP-D4 — the pin resolves once** `[proposed — gap §ordering]` · M×M
The pin resolves to one version when the grant is issued. A new result that arrives during the
run does not change the version in use. The report names the resolved result, so a reader
never has to re-resolve a pin.

**RP-D5 — replay is not bit-exact for repeated calls** `[proposed]` · M×M
When a recipe sends the same request several times in one run and the original got different
answers (bypass sampling), then replay returns the first recorded answer each time (CV-D6).
The docs and the report field `replay.repeated_key_collapses` (count) state this.

**RP-D6 — the rerunner's credentials pay for the misses** `[implied]` · M×M
Misses go through the rerunner's own provider connection, as any live call does. If the
rerunner has no connection for that provider, the usual credential error applies to that call.

**RP-D7 — pin-by-date boundaries** `[proposed]` · M×M
- A date-only `T` means the end of that day, UTC.
- A time with an offset is converted to UTC.
- A result whose `submitted_at` equals `T` exactly is included (≤ T).
- A `T` in the future resolves to the newest version.
- Ties on `submitted_at` break by the greater result `id`.

**RP-D8 — local mode** `[proposed]` · M×M
In `screamingface up`, the local scoreboard signs grants with a key that the local runtime
creates on first start, and passes its public key to the local gateway config. The WIRING unit
owns this (`ans:Q23`). With auth `disabled` (the dev and local fallback only, `ans:Q22`), the
gateway skips the subject check (CV-19). In production, auth is `cloudflare_headers`, and the
subject check always runs.

**RP-D9 — the replay run is submitted** `[stated prompt]` · H×M
When the replay run is submitted, the provenance is stored, and the run is labelled as a
replay (SC-D7).

## 4. Non-functional requirements

- A grant request takes ≤ 150 ms p99 (pin resolution plus an EdDSA sign) `[proposed]`.
- Replay hits add ≤ 30 ms p99 per call at the gateway (CV NFR). A replay of 5,000 calls that
  are all hits costs $0 in provider spend `[stated prompt]` (the cache is the point).
- Observability `[proposed]`:
  - scoreboard `scoreboard_replay_grants_total{result=issued|not_found|withdrawn|mismatch}`
  - the engine replay hit and miss counts, as the counter frame of `contracts.md` C12. They stay
    in process: the run mode has no metrics exporter (D7, X-15).
  - the report fields in RP-H1
- Security `[proposed]`:
  - The grant is a JWS (EdDSA) with `iss:"scoreboard"`, `aud:"aigateway"`,
    `sub:<caller identity>`, `vid`, `rid` (result id), `exp`, `iat`, and a `kid` header.
  - The scoreboard signing key `SCOREBOARD_REPLAY_GRANT_SIGNING_KEY` comes from a Secret.
  - The gateway holds the public keys only.

## 5. Out of scope

- A diff UI or a compare endpoint. The report keeps the baseline id so a later tool can join
  the two results.
- Replay from a GitHub-published archive into a gateway with no scoreboard (a future E8 or
  local issue).
- Per-candidate pins across several candidates (RP-E7).

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: the trust boundary first (access and grant rules), then the correctness of the pin
resolution, then the engine plumbing, then the SDK surface, then the E2E spine.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| RP-1 | `non_owner_private_pin_404_no_leak` | integration | [stated ans:Q4] RP-H4 | H×M | access check at resolve |
| RP-2 | `non_owner_non_redistributable_public_pin_404_owner_ok` | integration | [stated ans:Q6] RP-E2 | H×M | `Benchmark.redistributable` |
| RP-3 | `withdrawn_pin_410_for_non_owner_owner_ok` | integration | [stated ans:Q10] RP-E3 | H×L | join the publication state |
| RP-4 | `grant_claims_sub_aud_vid_rid_exp_12h_kid` | unit | [proposed] RP-D3 | H×M | signer port |
| RP-5 | `gateway_rejects_grant_reused_by_other_subject` | integration | [proposed] RP-D1 | H×M | CV-18 subject row |
| RP-6 | `pin_by_date_newest_at_or_before_T_across_revisions` | unit | [stated ans:Q7] RP-H2 | H×H | `ORDER BY submitted_at DESC, id DESC` |
| RP-7 | `pin_by_date_boundaries` (date-only, offset, equal-T, future, tie) | unit | [proposed] RP-D7 | M×M | |
| RP-8 | `pin_forms_resolve_result_score_name_revision` | unit | [proposed] RP-H1 | M×M | uses SR-20 |
| RP-9 | `unknown_pin_404_before_run_no_spend` | integration | [proposed] RP-E1 | H×M | the SDK raises before minting |
| RP-10 | `benchmark_mismatch_422` | unit | [proposed] RP-E4 | M×M | |
| RP-11 | `engine_carries_grant_opaquely_and_writes_header_last` | unit | [proposed] RP-D2 | H×M | a `RequestScope` field plus the job env |
| RP-12 | `identity_header_cannot_inject_replay_header` | unit | [proposed] RP-D2 | H×L | same rule as `X-Profile` |
| RP-13 | `engine_counts_version_hits_and_misses_into_report` | integration | [stated ans:Q13] RP-H5 | H×M | `RunCacheCounters.record` gets a version dimension |
| RP-14 | `grant_rejected_mid_run_fails_run_with_typed_error` | integration | [proposed] RP-E6 | M×L | map 403 `replay_grant_invalid` |
| RP-15 | `repeated_key_collapse_counted_in_report` | unit | [proposed] RP-D5 | M×M | |
| RP-16 | `sdk_evaluate_replay_requests_grant_then_runs` | unit (`httpx.MockTransport`) | [stated prompt] RP-H1 | H×H | new kwarg, sync and async |
| RP-17 | `sdk_multi_candidate_with_pin_raises` | unit | [proposed] RP-E7 | M×L | |
| RP-18 | `sdk_malformed_pin_raises_before_calls` | unit | [proposed] RP-E8 | M×L | pin parser shared with SR-20 |
| RP-19 | `sdk_scoreboard_down_raises_replay_unavailable` | unit | [proposed] RP-E5 | M×M | no silent fallback |
| RP-20 | `local_mode_grant_keys_wired_by_up` | integration | [proposed] RP-D8 | M×M | runtime config |
| RP-21 | E2E `submit_then_other_user_replays_all_hits_zero_cost_then_submit_labelled_replay` | E2E | [stated prompt] RP-H1 RP-D9 | H×H | the spine |
| ~~RP-22~~ | ~~E2E `changed_recipe_pin_by_date_partial_hits`~~ | ~~E2E~~ | [stated prompt] RP-H3 | ~~M×M~~ | Dropped (owner, 2026-09-30, Q30): no paid run is used as a test; covered by RP-6, RP-7, CV-17, RP-13, RP-21 |

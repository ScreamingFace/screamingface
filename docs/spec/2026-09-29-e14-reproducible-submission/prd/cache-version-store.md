# PRD: Cache version store — capture, freeze, replay lookup, archive (component)

**Source:** ticket §2 · ans:Q2, Q3, Q4, Q6, Q13 · **Priority:** P0 (the core of E14b)
**Lifecycle:** planned (new component in `apps/aigateway`). It changes the existing chat path.
**Owner:** unassigned

## 1. Flows served

- `prd/submit-and-cluster.md` freezes the cache version of a run at submit time (operation `freeze`).
- `prd/replay-pinned-run.md` serves version hits during a pinned run (operation `lookup`).
- `prd/publish-and-takedown.md` reads the bucket archive that this component writes.

## 2. Background and constraints

- "A submission records the cache version that belongs to it. One submission, one recipe, one
  cache version." `[stated prompt]`
- "Rerunning that exact recipe can use that cache version." `[stated prompt]`
- Irina: "Likely should pull cached results to a 'pinned' or 'published' repo rather than
  continuing to use the cache for their storage." `[stated prompt]`. So a version is a
  **copy**. It never points into the live cache.
- A version stores full prompts and outputs. Private versions are readable by the owner only
  `[stated ans:Q3]`.
- Private-board and gated-benchmark versions live in a private bucket, owner-only
  `[stated ans:Q6]`.
- On a replay miss, the call falls through to the live path and the run is marked partial
  `[stated ans:Q13]`.
- The gateway credential rules stay as they are: credentials only in `credential_blobs`; the
  `AIGATEWAY_SECRET_KEY` is never stored or logged (CLAUDE.md, Architecture).
- Data model: `CacheCaptureEntry`, `CacheVersion`, `CacheVersionEntry`, `CacheVersionBlob`,
  `VersionArchive` (`erd.md` §3).

### 2.1 Current behavior

- The chat route looks up the global cache before it resolves a credential (STAGE 1). It
  dispatches on a miss (STAGE 2) and writes the entry after a miss (STAGE 3). The write never
  fails the request `[existing apps/aigateway/src/aigateway/routes/chat.py:329-506]`.
- The cache key hashes provider, models, messages, system, keyed parameters and the prepared
  request, with no version dimension
  `[existing apps/aigateway/src/aigateway/core/request_cache/global_keys.py:257-292]`. A test
  enforces this `[existing apps/aigateway/tests/unit/test_global_cache_key.py:260-273]`.
- A cache row stores `key_hash`, `prompt_hash` and `response_json`, but not the messages
  `[existing apps/aigateway/src/aigateway/core/request_cache/models/request_cache_entry.py:14-15]`.
  Rows never expire (`expires_at = NULL`)
  `[existing apps/aigateway/src/aigateway/core/request_cache/models/request_cache_entry.py:22-25]`.
  So the **answers** of a run stay available with no time limit. What the cache lacks is the
  prompt text, the link from a run to its keys, and the answers of uncached calls
  (`erd.md` §3, preamble).
- The gateway publishes the cache outcome in `Cache-Status` and `X-AIGW-Cache*` headers
  `[existing apps/screamingface-engine/src/screamingface_engine/world/cache_readback.py:63-67]`.
- The engine forwards `traceparent` to the gateway on each call
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1061-1078]`.
  The SDK mints one trace per candidate run
  `[existing packages/screamingface/src/screamingface/_engine/transport.py:180-183]`.
- The e2e-replay "bless" script already cuts a per-board slice (full prompts and responses)
  from the rows that a run touched. It is the prototype of this component
  `[existing packages/screamingface/tests/e2e/fixtures/slice_snapshot.py]`.

**Delta.**
- A capture hook on the chat path. It writes the prompt per key (`RequestCachePrompt`) and
  one thin run-index row (`CacheCaptureEntry`). Both are kept forever `[stated ans:Q18]`.
- A replay stage before STAGE 1.
- The freeze and lookup services, a receipt signer, a grant verifier, and the archive exporter.

The global cache key stays unchanged. There is no purge job, so a freeze can happen at any
time after the run.

## 3. Scenarios and acceptance criteria

### 3.1 Behavior

**Capture.** For each chat request that carries a valid `traceparent`, the gateway:
1. writes the canonical request to `RequestCachePrompt` with
   `INSERT … ON CONFLICT (key_hash) DO NOTHING` (one prompt per key, for every outcome);
2. appends one thin `CacheCaptureEntry` for `(account_id, trace_id)`, with the `key_hash`,
   the order and the outcome. The answer goes inline only when no live-cache row holds it
   (`unstored`, `bypass`).

**Freeze.** `freeze(account_id, trace_id) → (CacheVersion, receipt)` reads the run index of
the trace. It joins each row to its prompt (`RequestCachePrompt`) and to its answer (the live
cache row, or the inline body). It copies the result into content-addressed blobs and entries
in one transaction, then signs a receipt. The freeze works at any time after the run, because
none of its inputs expire `[stated ans:Q18]`.

**Lookup.** `lookup(grant, request) → hit(response) | miss` finds the blob of the request's
`key_hash` in the version that the grant names.

**CV-H1** `[stated prompt]` — capture of a traced run.
Given a run with trace T sends 3 calls: a cache hit, a miss that is then stored, and a
`use-cache: false` bypass,
then 3 run-index rows exist for `(account, T)` with outcomes `hit`, `stored` and `bypass`.
Only the `bypass` row has an inline `response_json`, and no row holds prompt text. The 3
prompts are in `RequestCachePrompt`, one per `key_hash`.

**CV-H2** `[stated prompt]` `[stated ans:Q3]` — freeze.
Given the ledger of CV-H1,
when the owner calls `freeze(account, T)`,
then a `CacheVersion` exists with `call_count=3`, `entry_count=3`, `missing_count=0`,
`coverage_status=complete`. Each entry has the full request (from `RequestCachePrompt`) and
the full response. The response is the live row's `response_json` for `hit` and `stored`, and
the inline body for `bypass`.

**CV-H2b** `[stated ans:Q18]` — a late freeze.
Given the run of CV-H1 finished 6 months ago, and nobody pruned the cache,
when the owner calls `freeze(account, T)`,
then the result is the same as CV-H2, with `coverage_status=complete`.

**CV-H3** `[proposed]` — signed receipt.
Then `freeze` returns a receipt: a compact JWS (EdDSA, Ed25519) with the claims
`{iss:"aigateway", sub:<account identity>, vid:<version_id>, tid:<trace_id>,
sha:<archive_sha256>, n:<entry_count>, c:<call_count>, cov:<coverage_status>, iat}` and the
header `kid`. See `contracts.md` C3.

**CV-H4** `[stated prompt]` — replay hit.
Given version V holds the key K,
when a chat request carries a valid replay grant for V and its key is K,
then the gateway returns V's response for K without a credential lookup or a provider call.
The response has `Cache-Status: aigateway; hit; detail=version` and
`X-AIGW-Cache-Version: hit`.

**CV-H5** `[stated ans:Q13]` — replay miss falls through.
Given version V does not hold the key K,
when a request with a valid grant for V has key K,
then the request continues to STAGE 1 (the global cache), then to the provider as usual, and
the response has `X-AIGW-Cache-Version: miss`.

**CV-H6** `[stated ans:Q6]` — archive export.
Given version V is `frozen`,
then the exporter writes `cache-versions/<V>/entries.jsonl.gz` and `manifest.json` to the
private bucket, checks that the written bytes hash to `archive_sha256`, and sets `status=archived`.

### 3.2 Error paths

**CV-E1** `[proposed]` — freeze of an unknown trace.
When `freeze(account, T)` finds no ledger rows for `(account, T)`, then it fails with
`404 trace_not_captured`. Rows of another account are invisible, so the response is the same
404.

**CV-E2** `[proposed]` — the live row is gone at freeze time.
Given a `hit` or `stored` run-index row whose live-cache row an operator pruned before the
freeze (`[existing apps/aigateway/DEPLOYMENT.md:313-339]`),
then the freeze skips that call, counts it in `missing_count`, and sets
`coverage_status=partial`. The freeze still succeeds. This is the only way a late freeze can
lose calls, because nothing else expires.

**CV-E3** `[proposed]` — oversized version.
When a trace has more than 20,000 distinct entries, or the archive passes 1.5 GB, then the
freeze fails with `413 cache_version_too_large` and writes nothing (transaction rollback).
See `erd.md` §5.

**CV-E4** `[proposed]` — invalid grant.
When a chat request carries a replay grant that fails the signature check, has expired, has a
wrong `aud`, names an unknown version, or (in an authenticated mode) has a `sub` that is not
the caller, then the gateway rejects the request with `403 replay_grant_invalid` and a closed
`reason` (`signature|expired|audience|unknown_version|subject`). It does **not** fall through.
A bad grant is a caller error, not a miss.

**CV-E5** `[proposed]` — bucket down during the export.
When the bucket write fails, then the version stays `frozen`, the exporter retries with
exponential backoff and jitter (1 s base, 5 min cap), and replay still works, because replay
reads Postgres.

### 3.3 Derived scenarios (risk order)

**CV-D1 — capture must never fail or slow a chat request** `[proposed — gap §resilience]` · H×M
When the ledger insert fails (DB error, constraint), then the chat response is unchanged, the
failure is logged, and `aigw_capture_failures_total` increments. This is the same invariant as
the STAGE 3 cache write `[existing apps/aigateway/src/aigateway/routes/chat.py:495]`. The
capture adds ≤ 5 ms p99 to a request.

**CV-D2 — the ledger is account-scoped** `[proposed — gap §security]` · H×M
Given Bruno knows Ana's `trace_id`,
when Bruno calls `freeze(bruno, T_ana)`,
then he gets `404 trace_not_captured`. The `trace_id` is a client-minted value and is not a
secret. The account scope is the boundary.

**CV-D3 — freeze is idempotent** `[proposed — gap §per-flow/repeat]` · H×H
When the owner calls `freeze(account, T)` twice (for example, a retried submit),
then the second call returns the same version and a receipt with the same `vid` and `sha`.
Unique `(owner_account_id, trace_id)`. On a unique violation, re-read.

**CV-D4 — freeze of a trace that is still running** `[proposed — gap §ordering]` · M×L
Given the SDK freezes only after the run's terminal frame (`prd/submit-and-cluster.md`),
a late ledger row with an ordinal after the freeze can only come from a misbehaving client.
Such rows are not in the version, and the version does not change (I-R3 in the ERD).

**CV-D5 — calls without `traceparent`** `[proposed]` · M×M
When a chat request has no valid `traceparent` (for example, a direct call, or a report with
`trace_id = None`), then the gateway writes no ledger row, and a freeze for that run is
impossible. The submit then carries no version (`prd/submit-and-cluster.md` SC-D6).

**CV-D6 — repeated identical calls in one run** `[proposed]` · M×M
Given a run sends the same request twice and gets different responses (bypass sampling),
then the version keeps both blobs, and replay returns the one with the lowest ordinal
(`erd.md` §3.4). The replay flow documents this limitation (RP-D5).

**CV-D7 — errors are not frozen as answers** `[proposed]` · H×L
When a call failed (provider error, `outcome=error`), then the freeze counts it in
`missing_count` and stores no blob. A replay must never serve an error as a cached answer.

**CV-D8 — streaming calls** `[proposed]` · M×L
Streaming bypasses the cache and accounting today (`routes/chat.py`, streaming branch). A
streaming call gets a ledger row with `outcome=bypass` and no body. The freeze counts it as
missing. v1 does not capture stream bodies.

**CV-D9 — grant cache** `[proposed — gap §performance]` · M×M
The gateway caches verified grants in process for 60 s, keyed by the token hash, so a
5,000-call run verifies its grant about once per minute, not per call.

**CV-D10 — replay output is untrusted text** `[proposed — gap §security]` · M×L
The blob content is model output. The gateway returns it as data only and never interprets
it. A published archive can hold prompt-injection text; consumers treat it as untrusted.

**CV-D11 — prompts are stored once per key** `[proposed — gap §performance]` · M×M
Given 10 reruns of the same recipe send the same 1,000 requests,
then `RequestCachePrompt` holds 1,000 rows, not 10,000. The run index holds 10,000 thin rows.
Two concurrent first writes of one key leave one row (`ON CONFLICT DO NOTHING`), and neither
call fails.

**CV-D13 — an operator prune stays consistent** `[proposed — gap §per-element/store]` · M×L
When an operator prunes `request_cache_entries`, the prune also deletes the matching
`RequestCachePrompt` rows, **except** keys that a `CacheCaptureEntry` still references.
Reason: the run index is kept forever `[stated ans:Q18]`, so its prompts must stay for a later
freeze. The answer of a pruned key is still lost (CV-E2).

**CV-D12 — signing key rotation** `[proposed — gap §external/credentials]` · M×L
Receipts carry `kid`, derived as `sha256(<raw 32-byte public key>).hexdigest()[:16]` (D7, X-4;
`contracts.md` C3). The scoreboard accepts the current key and the previous key, so a
rotation does not break submits that are in flight.

**Not applicable:** cancel (freeze is one transaction). Empty state: freeze of an empty
ledger is CV-E1.

## 4. Non-functional requirements

- Capture: ≤ 5 ms p99 added per chat request, for both writes (the prompt upsert and the
  run-index insert) `[proposed]`.
  The two writes run in one transaction, so each call gives one commit (`ans:Q31`). The CI bench
  runs Postgres with durable commit off (`fsync`, `synchronous_commit` and `full_page_writes` off). It measures the
  capture cost, not the host disk. Production commit latency is a deploy property of the database.
- Replay hit: ≤ 30 ms p99 (grant cache plus one indexed lookup), with no provider call
  `[proposed]`.
- Freeze: ≤ 10 s for 5,000 entries `[proposed]`. The HTTP timeout is 60 s (`contracts.md` C2).
- Storage: see `erd.md` §5, with the tripwire at 200 GB of blobs.
- Security `[proposed]`:
  - The receipt signing key `AIGATEWAY_RECEIPT_SIGNING_KEY` (Ed25519, standard base64 of the
    raw 32-byte key, no PEM) comes from a Kubernetes Secret. It is never logged.
  - The grant verification key `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS` (JSON map `{kid: base64
    of the raw 32-byte public key}`) is config.
  - The WIRING unit adds these values and the Secret templates to the aigateway chart
    (`ans:Q23`).
  - The bucket write credentials are for the gateway only.
  - Bucket objects use server-side encryption.
- Observability `[proposed]`:
  - `aigw_capture_rows_total{outcome}`, `aigw_capture_failures_total`
  - `aigw_request_cache_prompts_total` (a gauge), `aigw_capture_index_bytes` (for the `erd.md` §5 tripwire)
  - `aigw_cache_version_freeze_seconds`, `aigw_cache_version_entries`
  - `aigw_cache_version_missing_total`
  - `aigw_replay_lookups_total{result=hit|miss|invalid_grant}`
  - `aigw_version_export_pending` (a gauge, with an alert when it is above 0 for 30 min)

## 5. Out of scope

- A version dimension in the global cache key. It is rejected, so the no-variant test stays
  `[existing apps/aigateway/tests/unit/test_global_cache_key.py:260-273]`.
- Capturing streaming bodies (CV-D8).
- Version GC (`erd.md` §3.6).
- Import of a published archive into a gateway from GitHub. A future E8 or local-runtime
  issue.

## 6. Open questions

None. DQ-2 is decided: the run index and the prompts are kept forever, so a freeze has no
deadline (`ans:Q18`).

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: characterization first (the cache path must not change), then the data-integrity core
(freeze correctness, idempotency, account scope), then the hot-path invariants, then replay,
then the export.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| CV-1 | CHAR `global_key_has_no_variant_dimension` (already exists; keep it) | unit | [existing test_global_cache_key.py:260] | H×L | none: must stay green |
| CV-2 | CHAR `cache_hit_returns_before_credential_resolution` | integration | [existing routes/chat.py:329] | H×L | none |
| CV-3 | `capture_failure_does_not_change_chat_response` (the ledger insert raises) | integration | [proposed] CV-D1 | H×M | wrap it like `store_global_response` |
| CV-4 | `capture_writes_one_row_per_traced_call_with_outcome` | integration | [stated prompt] CV-H1 | H×H | hook after STAGE 1 and STAGE 3 |
| CV-5 | `capture_index_row_is_thin_body_inline_only_for_unstored_and_bypass` | unit | [proposed] CV-H1 | M×M | outcome switch; no prompt column |
| CV-6 | `untraced_call_writes_no_capture_row` | unit | [proposed] CV-D5 | M×M | parse `traceparent` |
| CV-7 | `freeze_copies_full_request_and_response_for_each_call` | integration | [stated ans:Q3] CV-H2 | H×H | join the ledger with the live cache |
| CV-8 | `freeze_is_idempotent_same_vid_same_sha` | integration | [proposed] CV-D3 | H×H | unique `(owner, trace)`, re-read |
| CV-9 | `freeze_of_other_accounts_trace_is_404` | integration | [proposed] CV-D2 | H×M | filter by account |
| CV-10 | `freeze_counts_pruned_row_as_missing_partial` | integration | [proposed] CV-E2 | H×M | left join, count nulls |
| CV-27 | `late_freeze_after_six_months_is_complete` (clock moved forward) | integration | [stated ans:Q18] CV-H2b | H×M | no expiry on any input |
| CV-11 | `freeze_never_stores_error_outcome_as_blob` | unit | [proposed] CV-D7 | H×L | skip `error` |
| CV-12 | `archive_bytes_are_canonical_and_hash_matches` (property: freeze twice, same bytes) | unit | [proposed] erd §3.5 | H×M | sorted keys, gzip `mtime=0` |
| CV-13 | `receipt_is_eddsa_jws_with_required_claims_and_kid` | unit | [proposed] CV-H3 | H×M | PyJWT with EdDSA |
| CV-14 | `freeze_too_large_413_and_nothing_written` | integration | [proposed] CV-E3 | M×L | count first, roll back |
| CV-15 | `freeze_unknown_trace_404` | unit | [proposed] CV-E1 | M×L | |
| CV-16 | `valid_grant_hit_serves_version_without_provider_call` | integration | [stated prompt] CV-H4 | H×H | STAGE 0 before STAGE 1 |
| CV-17 | `valid_grant_miss_falls_through_and_marks_miss` | integration | [stated ans:Q13] CV-H5 | H×H | continue the pipeline |
| CV-18 | `invalid_grant_rejects_403_with_closed_reason` (table: signature, expired, audience, unknown version, subject) | unit | [proposed] CV-E4 | H×M | verifier port |
| CV-19 | `grant_subject_check_skipped_when_auth_disabled` | unit | [proposed] | M×L | mode switch |
| CV-20 | `duplicate_key_replay_returns_lowest_ordinal` | unit | [proposed] CV-D6 | M×M | `ORDER BY first_ordinal LIMIT 1` |
| CV-21 | `verified_grant_cached_60s` | unit | [proposed] CV-D9 | M×M | TTL cache keyed by token hash |
| CV-22 | `export_writes_pair_and_sets_archived` | integration (MinIO/Garage testcontainer) | [stated ans:Q6] CV-H6 | H×M | outbox by `status=frozen` |
| CV-23 | `export_retries_when_bucket_down_replay_still_works` | integration | [proposed] CV-E5 | M×M | backoff; replay reads DB |
| CV-24 | `prompt_stored_once_per_key_concurrent_first_writes_one_row` | integration | [proposed] CV-D11 | M×M | `ON CONFLICT DO NOTHING` |
| CV-28 | `operator_prune_keeps_prompts_referenced_by_run_index` | integration | [proposed] CV-D13 | M×L | anti-join on `CacheCaptureEntry` |
| CV-25 | `receipt_signed_with_rotated_key_verifies_with_both_kids` | unit | [proposed] CV-D12 | M×L | kid map |
| CV-26 | `streaming_call_captured_as_bypass_without_body` | unit | [proposed] CV-D8 | M×L | |

**Refactor notes.**
- Put the capture, freeze and lookup services in `aigateway.core.cache_versions`.
- Put the grant verifier and the receipt signer behind ports (`ReplayGrantVerifier`,
  `ReceiptSigner`), and put the bucket behind a `VersionArchiveStore` port with S3 and
  filesystem adapters. The filesystem adapter is for local mode.
- The chat route calls the ports only. No plugin imports them (hexagonal rule).

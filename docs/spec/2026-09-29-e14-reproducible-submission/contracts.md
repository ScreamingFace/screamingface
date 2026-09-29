# Contracts — E14 reproducible submission (OME-1307)

This document has one section per connection. The shapes are `[proposed]` unless a tag says
otherwise. Test ids point to the PRD TDD tables (`SR-`, `CV-`, `MD-`, `SC-`, `RP-`, `PB-`).

## 0. Topology of the new hops

```mermaid
flowchart LR
  SDK[SDK / client]
  ENG[engine control plane + runner]
  GW[aigateway]
  SB[scoreboard]
  BK[(private bucket)]
  GH[(GitHub repo)]
  SDK -- C1 run + replay grant --> ENG
  SDK -- C2a freeze --> ENG
  ENG -- C2b freeze --> GW
  ENG -- C9 chat call + grant header --> GW
  SDK -- C4 submit + receipt --> SB
  SDK -- C5 metadata PATCH --> SB
  SDK -- C6 replay grant --> SB
  SDK -- C10 publish / results --> SB
  GW -- C8a write archive --> BK
  SB -- C8b read archive --> BK
  SB -- C7 releases --> GH
```

There is no scoreboard ↔ gateway connection. Trust between them goes through two signed
tokens: the **receipt** (C3, gateway → scoreboard) and the **grant** (C6, scoreboard →
gateway). See DR-2.

## C1 — Run with a replay grant — SDK → engine, sync, HTTPS + WebSocket

- **Shape.** The existing `POST /token` and the WebSocket attach
  `[existing packages/screamingface/src/screamingface/_engine/transport.py:858-887]`, plus one
  optional request header on `POST /token`: `X-SF-Cache-Replay: <grant JWS>` (≤ 2,048 bytes).
- **Engine handling.** The control plane copies the value into the run's job environment. The
  child binds it into `RequestScope.replay_grant`. The engine never decodes it (RP-D2).
- **Policies.** Same timeouts and retries as today. The header adds no retry.
- **Failure.** A header over 2,048 bytes gets `431` from the engine, and the SDK raises before
  the run. A missing header means a normal run.
- **Contract tests.** RP-11, RP-12, RP-16.

## C2a — Freeze — SDK → engine, sync, HTTPS

```http
POST /v1/cache-versions
Content-Type: application/json
{"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"}

201 | 200 (idempotent re-freeze)
{"receipt": "<JWS>", "cache_version_id": "uuid", "entry_count": 412,
 "call_count": 420, "missing_count": 8, "coverage_status": "partial",
 "archive_sha256": "64-hex"}
```

- **Auth.** The caller identity comes from the edge (`X-User-Email`), the same as the other
  engine routes. The engine forwards it as identity headers.
- **Policies.** SDK timeout 60 s. One retry on a connection error or a 502/503/504, with
  1–3 s jitter. Safe to retry, because the freeze is idempotent (CV-D3).
- **Failure (caller).** Any non-2xx result, or a timeout after the retry, means the SDK
  submits without a version and warns (SC-E1).
- **Contract tests.** SC-18, SC-19, SC-21.

## C2b — Freeze — engine → aigateway, sync, HTTP (ClusterIP :9105)

- **Shape.** The same body and response as C2a. Gateway route: `POST /v1/cache-versions`.
- **Auth.** The existing gateway auth modes. The account is resolved from the identity
  headers, as on the chat path. The request must pass the NetworkPolicy, which already admits
  `url4-cloud` `[existing apps/aigateway/charts/aigateway/templates/networkpolicy.yaml]`.
- **Errors.** `404 trace_not_captured` (CV-E1, CV-D2), `413 cache_version_too_large` (CV-E3),
  `503 capture_disabled` (a kill switch, `AIGW_CACHE_VERSIONS_ENABLED=false`).
- **Policies.** Engine timeout 55 s, less than the SDK's 60 s, so the engine answers first. No
  engine retry; the SDK owns the retry.
- **Contract tests.** CV-7, CV-8, CV-9, CV-14, CV-15, SC-21.

## C3 — Cache version receipt — aigateway → (SDK) → scoreboard, signed token

A compact JWS with `alg: EdDSA` (Ed25519), header `kid`, and these claims:

```json
{"iss": "aigateway", "aud": "scoreboard", "sub": "<caller identity>",
 "vid": "uuid", "tid": "32-hex", "sha": "64-hex",
 "n": 412, "c": 420, "cov": "complete|partial", "iat": 1790000000}
```

- **Verifier (scoreboard).** Check the signature against `SCOREBOARD_RECEIPT_PUBLIC_KEYS`
  (`kid → key`, current plus previous). Check `aud`. Check `sub` equals the verified
  submitter (in `disabled` mode, skip this). Check `tid` equals the report `trace_id`. The
  receipt has no `exp`: it attests a fact about an immutable version, and replay protection
  comes from the unique `cache_version_id` (SC-E4).
- **Failure.** `422 invalid_cache_version_receipt`, `403 cache_version_not_yours`,
  `409 cache_version_already_bound`.
- **Contract tests.** CV-13, CV-25, SC-4, SC-5, SC-6.

## C4 — Submit — SDK → scoreboard, sync, HTTPS

- **Shape.** Today's `ScoreSubmission`
  `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:366]`, plus these optional
  fields:

```json
{"paper_url": "https://…", "revision_of": "kevins-best",
 "cache_version_receipt": "<JWS>",
 "replay": {"result_id": "uuid", "cache_version_id": "uuid",
            "hits": 412, "misses": 8, "repeated_key_collapses": 0,
            "pinned_baseline_result_id": "uuid|null"}}
```

- **Response.** Today's `ScoreSchema` for the head, plus:

```json
{"paper_url": "…", "metadata_revision": 1,
 "reported_result": {"id": "uuid", "is_original": true, "reporter": "…",
                     "cache_version": {"id": "uuid", "sha256": "…", "entry_count": 412,
                                       "call_count": 420, "coverage_status": "complete"},
                     "publication_state": "private"},
 "reported_results_count": 1,
 "notices": [{"code": "system_already_named|clustered_under", "...": "..."}]}
```

- **Status.** `201` for a new head or a new reported result. `200` for an idempotent
  `run_id` replay.
- **Idempotency.** `Idempotency-Key: <run_id>`, unchanged
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:106]`. It is
  now enforced by the unique `ReportedResult.run_id`.
- **Errors.** Today's errors, plus the C3 errors, plus the registry errors (SR-E1 to SR-E5).
- **Policies.** SDK timeout 30 s. Retry on a connection error or a 5xx, twice with backoff.
  Safe, because of the idempotency key.
- **Trust.** The replay block is a client claim. The scoreboard checks that the result id
  exists, that the claimed `cache_version_id` belongs to it, and that the caller could have
  gotten a grant for it. Otherwise `422 invalid_replay_claim`. The hit and miss counts are
  stored as reported, and are labelled "reported by client" in the results list.
- **Contract tests.** SC-3 to SC-16, SC-18.

## C5 — Metadata edit — SDK → scoreboard, sync, HTTPS

```http
PATCH /v1/scores/{score_id}
If-Match: "3"
Content-Type: application/json
{"authors": ["ana@x.org", "bruno@y.org"], "paper_url": "https://…"}

200  ETag: "4"   <ScoreSchema>
401 identity_not_verified | 403 not_submission_owner | 404 | 412 metadata_revision_conflict
| 422 (field errors / field_not_editable) | 428 precondition_required

GET /v1/scores/{score_id}/metadata-history?cursor=…&limit=50
200 {"events": [{"actor": "…", "at": "…", "from_revision": 3, "to_revision": 4,
                 "before": {...}, "after": {...}}], "next_cursor": "…|null"}
```

- **Policies.** SDK timeout 15 s. One retry on a connection error. It is safe by MD-D4 (a
  resend of equal values returns 200).
- **Contract tests.** MD-3 to MD-19.

## C6 — Replay grant — SDK → scoreboard, sync, HTTPS; the grant token scoreboard → (engine) → aigateway

```http
POST /v1/replay-grants
{"pin": "kevins-best@2026-09-01", "benchmark_id": "gsm8k"}

200 {"grant": "<JWS>", "result_id": "uuid", "score_id": "uuid",
     "cache_version_id": "uuid", "expires_at": "RFC3339"}
404 replay_pin_not_found | 410 cache_version_withdrawn | 422 invalid_replay_pin
| 422 replay_benchmark_mismatch
```

The grant JWS has `alg: EdDSA`, header `kid`, and these claims:
`{"iss":"scoreboard","aud":"aigateway","sub":"<caller identity>","vid":"uuid","rid":"uuid","iat":…,"exp":iat+43200}`.

- **Verifier (gateway).** Check against `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS`. Check `aud`,
  `exp` (±60 s skew allowance), that `vid` exists, and that `sub` equals the caller (skipped
  when auth is `disabled`). Cache the result for 60 s (CV-D9).
- **Policies.** SDK timeout 10 s. No fallback (RP-E5).
- **Contract tests.** RP-1 to RP-10, RP-4, CV-18, CV-19, CV-21.

## C7 — Releases — scoreboard worker → GitHub REST API, sync, HTTPS

- **Calls.**
  - `GET /repos/{o}/{r}/releases/tags/cv-<vid>`
  - `POST /repos/{o}/{r}/releases` with `{tag_name, name, body, draft:false}`
  - `POST {upload_url}?name=entries.jsonl.gz` and `?name=manifest.json`
  - `DELETE /repos/{o}/{r}/releases/{id}`
  - `DELETE /repos/{o}/{r}/git/refs/tags/cv-<vid>`
- **Auth.** A GitHub App installation token, with contents write on this one repo, minted per
  job (PB-D7).
- **Policies.** Timeout 30 s per API call and 120 s per asset upload. Retry on 5xx, 429 and
  secondary-limit 403, honoring `Retry-After`, with the backoff of PB-E4. Idempotency through
  the deterministic tag plus the get-by-tag check (PB-D1).
- **Failure.** See PB-E4, PB-D1, PB-D4.
- **Contract tests.** PB-20 (recorded fixtures), PB-22 (sandbox repo, nightly).

## C8a / C8b — Archive — aigateway → bucket (write), scoreboard → bucket (read), S3 API

- **Objects.** `cache-versions/<vid>/entries.jsonl.gz`, `cache-versions/<vid>/manifest.json`
  (`erd.md` §3.5). Written once, and never overwritten (write with `If-None-Match: *`, or
  check existence first on Garage).
- **Credentials.** The gateway can write the prefix. The scoreboard can read the prefix
  (PB-D8). Server-side encryption is on.
- **Policies.** Gateway: export retries with backoff (CV-E5). Scoreboard: read timeout 60 s,
  with a digest check before any use (PB-E5).
- **Local mode.** The filesystem adapter of the `VersionArchiveStore` port, under the local
  runtime data directory.
- **Contract tests.** CV-22, CV-23, PB-3.

## C9 — Chat call — engine → aigateway, sync, HTTP (extends the existing call)

- **New request header.** `X-AIGW-Cache-Replay: <grant>`, a gateway-owned header that the
  connector writes last (RP-D2), next to `X-Profile` and `traceparent`
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1048-1078]`.
- **New response header.** `X-AIGW-Cache-Version: hit|miss`. On a hit, the response also has
  `Cache-Status: aigateway; hit; detail=version`
  `[existing apps/screamingface-engine/src/screamingface_engine/world/cache_readback.py:63-67]`.
- **Capture.** It needs no new request field. The gateway uses the existing `traceparent`
  (CV-H1).
- **Errors.** `403 replay_grant_invalid` with a `reason` (CV-E4). The engine maps it to a
  typed run failure (RP-14).
- **Policies.** Unchanged: 1 transport retry with backoff
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:92-100]`.
- **Contract tests.** CV-3, CV-4, CV-16, CV-17, RP-13, RP-14.

## C10 — Results, publish, withdraw — SDK / admin → scoreboard, sync, HTTPS

```http
GET  /v1/scores/{score_id}/results?cursor=…&limit=50          → 200 {"results": [...], "next_cursor": …}
POST /v1/results/{result_id}/publish                          → 202 {"state": "requested"} | 200 (no-op)
                                                                 409 not_publishable|withdrawn · 403 · 503 publish_unavailable
POST /v1/admin/results/{result_id}/withdraw {"reason": "…"}   → 200 {"state": "withdrawn"} · 403 admin_required
```

- **Contract tests.** SC-17, PB-1, PB-2, PB-6, PB-10, PB-12, PB-13, PB-16, PB-19, PB-21.

## C11 — Dependencies (layering rules)

| Rule | Enforcement |
|---|---|
| `url4.fingerprint` is pure: no I/O and no imports from the SDK, the engine or the scoreboard. | A unit test imports the module in isolation. It is added to the existing layering check `.claude/scripts/check_layering.py`. |
| The scoreboard may import `url4` (new). The scoreboard never imports `screamingface` (the SDK). | Layering-check rule and a test. |
| The engine never decodes the replay grant. Only `world/connector.py` writes the header. | Layering check: no `jwt` import under `screamingface_engine/`. Plus RP-11. |
| The gateway chat route reaches versions only through the ports `ReplayGrantVerifier`, `CacheVersionLookup` and `CaptureSink`. No provider plugin imports `core.cache_versions`. | Layering-check rule (hexagonal: core never imports plugins, and plugins do not reach into core stores). |
| The scoreboard reaches GitHub only through the `ReleasePublisher` port, and the bucket through the `VersionArchiveReader` port. | Layering-check rule. |

## Decision records

### DR-1 — A version is a copy in the gateway, not a dimension of the live cache key

- **Decision.** Copy the run's calls into immutable, content-addressed version tables at
  freeze time.
- **Best rejected alternative.** Add a version field to the global cache key.
- **Why.** Irina asked for a "pinned or published repo" instead of the live cache
  `[stated prompt]`. The live cache has no bound and can be pruned
  `[existing apps/aigateway/DEPLOYMENT.md:247-248]`. A key-version dimension would also break
  the deliberate no-variant invariant
  `[existing apps/aigateway/tests/unit/test_global_cache_key.py:260-273]`.
- **Cost accepted.** The storage duplicates live-cache rows (cut down by blob dedup).
- **Reversibility.** Costly: stored versions are research artifacts.
- **Change when.** Blob storage passes 200 GB (`erd.md` §5).

### DR-2 — Signed receipt plus signed grant, with no scoreboard ↔ gateway API

- **Decision.** The gateway signs receipts. The scoreboard signs grants. Each side verifies
  the other with public keys.
- **Best rejected alternative.** An internal scoreboard → gateway API (verify the version at
  submit; set the visibility flag on publish or withdraw).
- **Why.**
  - It avoids dual writes (a visibility flag in two databases would need an outbox).
  - It avoids a new network edge, and temporal coupling on the submit path.
  - The gateway stays unaware of the scoreboard (hexagonal ownership).
- **Cost accepted.** Two Ed25519 keypairs to manage and rotate. A takedown takes effect for
  issued grants only when they expire (≤ 12 h, RP-D3).
- **Reversibility.** Two-way door: the token formats are internal.
- **Change when.** A takedown must take effect within minutes, or the gateway needs other
  scoreboard state. Then add a pull-based revocation list.

### DR-3 — The gateway Postgres is the source of truth for replay; the bucket holds the archive

- **Decision.** Replay reads the gateway Postgres. The bucket holds the canonical archive for
  publishing and owner download (`ans:Q6`).
- **Best rejected alternative.** A bucket-only store, loading each archive into memory for a
  replay.
- **Why.** An indexed per-call lookup (≤ 30 ms), with no multi-MB load per run and no memory
  pressure across replicas.
- **Cost accepted.** Two stores. Divergence is detected by the digest check (PB-E5).
- **Reversibility.** Two-way door.
- **Change when.** The same trigger as DR-1.

### DR-4 — Freeze at submit time, through the engine

- **Decision.** The SDK asks the engine to freeze right before it submits.
- **Best rejected alternative.** The engine freezes every run automatically at its end.
- **Why.** Only submitted runs cost version storage, and the gateway stays ClusterIP-only (the
  engine is the client's single door, as with `/v1/connections`
  `[existing apps/screamingface-engine/src/screamingface_engine/connections/aigateway.py:67]`).
- **Cost accepted.** The gateway keeps a thin run index and one prompt per cache key forever
  (`ans:Q18`, ~33 GB per year for the index, `erd.md` §5), so a freeze has no deadline.
- **Reversibility.** Two-way door.
- **Change when.** The run index passes its `erd.md` §5 tripwire (then partition it), or users
  want a version for runs they never submit (then freeze at run end, with a version GC and a
  bind signal).

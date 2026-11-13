# Attachments by blob reference, engine to gateway

Status: draft, 2026-11-11. Owner: Sergey Bershadsky. Evidence: the research doc
"Attachment memory cost: proof and storage options"
(https://claude.ai/artifact/USXsTTKz3VuEdjpGoyZr6k), measured on 2026-11-11.

**Baseline.** This builds on the OME-1529 image-input stack, which is not on `main` yet: url4 run
attachments and caps (OME-1543, #1587), the engine's attachment parts (OME-1545, #1588) and run
file admission (OME-1809). File paths below are as they stand on that stack. No unit of this spec
starts before those merge.

## 1. Why

Today every model call that carries a url4 attachment rebuilds the file as inline base64 twice,
in the engine and again in the gateway. Nothing is shared between calls. Measured with one
7.9 MB picture:

| Where | Cost per in-flight call | 20 parallel calls | Limit it runs into |
| --- | --- | --- | --- |
| Engine | ~21 MB, plus ~30 ms of event-loop time | 443 MB peak, 0.6 s stall | 2,560 Mi per run slot |
| Gateway | ~24 MB (model of the chat route) | 495 MB Python, 730 MB RSS | 512 Mi pod, one replica |

A waiting gateway request already holds its whole body and its parsed JSON, so the gateway's
per-provider limit of 4 upstream calls does not bound memory.

The cost scales with fan-out, not with the run's cap, so the 8 MB cap cannot rise safely. A
separate small fix lowers the url4 cap to about 6,000,000 bytes so admitted runs fit the
gateway's 8 MiB body cap. This spec is what lets it rise again.

## 2. Goals

- G1. Engine memory per model call does not depend on the attachment's size. The run holds each
  attachment's bytes at most once.
- G2. A gateway request waiting for an upstream slot holds no attachment bytes.
- G3. The gateway holds each attachment's base64 text once per process, shared by all its
  requests, plus one serialised provider body per upstream call in flight.
- G4. The per-run attachment cap rises to 20,000,000 decoded bytes. One file can be up to that
  size.
- G5. Same answers, same cache hits, same frozen-copy replays as the inline path for the same
  files.

## 3. Non-goals

- Provider file uploads (Anthropic Files API, OpenAI Files, Gemini Files). The 20 MB target fits
  every provider's inline request limit, so they are not needed yet.
- Zero-copy inside url4. url4 may keep holding each attachment once for the run (G1 allows it).
- Benchmark Case pictures. They travel as base64 inside the Case's message envelope (OME-1678),
  not in url4's `attachments[]`, and stay inline (owner, 2026-11-11). The importer bounds them at
  8,000,000 bytes per Case.
- Changing how SDK users or other callers send pictures to the gateway directly. Inline `data:`
  URIs stay supported, unchanged.
- Streaming the gateway's upstream request body. LiteLLM and the provider plugins build their
  bodies in memory; G3 accepts one body per upstream call.

## 4. Anti-goals: this fails even if it works when

- The gateway can be made to dial an address a caller chooses. `media_intake.py`'s invariant
  stands: a caller never picks what the gateway fetches.
- A blob grant, a log line or an error carries the run id (it is the run's bearer capability),
  the tenant's email, or file bytes.
- A digest alone authorizes a read. A digest is guessable whenever the content is.
- A grant minted for one run reads another run's blob.
- The inline path regresses for callers that do not use references.

## 5. Design

### 5.1 Overview

1. Every url4 attachment of an engine run lands in the run blob store (OME-1540) before the
   first model call: blobs uploaded with `PUT /blob/sha256/{digest}` are already there, and
   `https://` attachment sources are written through as they are fetched (new).
2. The engine sends each attachment to the gateway as a blob reference part, never as base64,
   when the gateway is configured to accept references (5.6).
3. The engine attaches a short-lived grant to each request. The grant lets the gateway read
   exactly the referenced blobs of this run.
4. The gateway checks the request shape, runs the cache lookup on the reference form, and waits
   for its upstream slot holding only the small JSON.
5. Inside the slot, just before dispatch, the gateway resolves each reference. It fetches the
   blob once from its one configured blob source, verifies the digest, encodes base64 once per
   process and reuses it across requests. Then it builds the provider body as today.

### 5.2 The reference part (wire format, engine to gateway)

An attachment is one content part, in the same position F2 puts inline parts today:

```json
{"type": "image_url", "image_url": {"url": "blob:sha256/<64 hex>", "detail": "high"},
 "x_media_type": "image/png", "x_size": 7900000}
{"type": "file", "file": {"file_data": "blob:sha256/<64 hex>", "filename": "a.pdf"},
 "x_media_type": "application/pdf", "x_size": 1200000}
```

- `blob:sha256/<hex>` is url4's existing blob-ref spelling. It is not a URL; the gateway never
  treats it as one.
- `x_media_type` is required. The gateway's modality backstop (OME-1807) and per-type policy
  read it, since they can no longer read it off a `data:` header.
- `x_size` is the decoded size. The gateway uses it for admission (5.5) before any fetch, and
  refuses the request if the fetched bytes differ.
- Names prefixed `x_` are a placeholder for the builder to settle with the gateway's part
  parser; the fields themselves are the contract.

### 5.3 The grant (engine to gateway to engine)

- Sent once per request in a header, `X-SF-Blob-Grant`. It covers every reference in that
  request.
- It binds: the blob scope (tenant and run), the set of digests the request references, and an
  expiry. The process that runs the connector mints it: the App in local and in-process modes,
  the worker pod under `runner="queue"`. The key is a new engine secret, separate from the
  artifact signing key, delivered to the worker through the job env the way
  `URL4_CLOUD_ARTIFACT_SIGNING_KEY` already is (author's call). The construction follows
  `artifacts/signing.py` (HMAC, domain-separated) under a new prefix.
- The scope must not be readable by the gateway. The grant is encrypted and authenticated (an
  AEAD) or is an opaque handle the App resolves; the builder picks. Logs on both sides record a
  grant fingerprint, never the grant.
- Expiry: long enough to cover the request's upstream retries and queueing. The builder sets it
  from the connector's deadline (`_current_deadline`), with a floor of 5 minutes.
- The gateway treats the grant as opaque. It passes it back to the engine with each blob read.
  It never stores it: not in the request cache, not in a frozen-copy entry, not in logs.

### 5.4 Blob reads (gateway to engine App)

- The gateway has one configured blob source, `AIGW_BLOB_SOURCE_URL` (origin only, refused at
  startup otherwise, like `S3ObjectStoreConfig`). With it unset, the gateway refuses reference
  parts with a typed 422, and the engine falls back to inline (5.6).
- Read: `GET <source>/blob/sha256/<hex>` with the grant as the credential. The App accepts a
  grant as an alternative to `URL4-Capability` on this route only, checks that the digest is in
  the grant, and reads under the grant's scope. Any mismatch is the same 404 a missing blob
  gives.
- The App streams the body, so serving a 20 MB blob does not hold it whole. This is new work:
  today `get_blob` reads the whole blob and verifies it before answering. The streamed read keeps
  verify-on-read by hashing while it streams and aborting the response on a mismatch (author's call;
  the client also verifies, below).
- The gateway reads with a byte bound of `x_size`, verifies SHA-256 while reading, and refuses a
  short, long or mismatched body as permanent, before any upstream spend. The gateway gains the
  `x.blob_digest_mismatch` code, spelled as the engine and url4 spell it.

### 5.5 Gateway memory model

- Resolution happens inside the provider's upstream slot (the per-provider limit, default 4),
  after the cache lookup misses. Waiting requests hold only their JSON (G2).
- A per-process cache keyed by digest holds each file's base64 text once, shared by every
  request that references it (G3). It is bounded in bytes, evicts unreferenced entries first,
  and is never written to disk.
- A gateway-wide byte budget admits upstream dispatches by their resolved size: a request whose
  attachments would push in-flight bytes past the budget waits for room. It never fails for
  memory alone; a request larger than the whole budget is refused as permanent `request_too_large`.
  The budget and the pod's memory limit are set together. Sizing for 20 MB files: 4 providers × 4
  slots × ~27 MB serialised body is about 430 MB at worst, which does not fit 512 Mi with the
  process baseline. The builder either raises the gateway's memory limit or sets the budget below
  that worst case, and records the numbers.
- `AIGW_MAX_REQUEST_BYTES` (8 MiB) applies to the body the caller sends. A reference request is a
  few KB, so it passes. The upstream body is bounded by the resolved-size check against the run
  cap instead.

### 5.6 Engine side

- Write-through: an `https://` attachment source is written to the run blob store as it is
  fetched, under its digest. Only the types the App's blob policy stores (png, jpeg, gif, webp,
  pdf, signature-checked) are written through; any other type is already refused by the gateway's
  per-type policy, so the run refuses it at admission instead (author's call). The blob store gets a chunked read and a chunked write (S3: ranged
  GET and multipart or single PUT; filesystem: file streams). `blob_max_bytes` rises with the cap.
- The connector builds reference parts from the run's `attachments[]` (digest, media type,
  size) and never reads attachment bytes for a model call. Memory per call is the small JSON
  (G1).
- Fallback: when the gateway does not accept references (config, or the gateway's typed 422) or
  the deployment has no blob store (local mode without one), the connector sends inline, with the
  bytes verified and encoded once per run and shared across calls, and the body streamed from
  that shared encoding. The research measured this at 19 MB for 20 calls against 438 MB today.
- The cap follows the path (owner, 2026-11-11). A run whose attachments go by reference is capped
  at 20,000,000 bytes; a run on the inline path keeps the lower cap (about 6,000,000 bytes) that
  fits the gateway's 8 MiB body cap. url4's run admission takes the cap from the engine, which
  knows its path from configuration before the run starts. The gateway's body cap does not
  change.
- Configuration is explicit: the engine sends references only when its gateway config says the
  gateway accepts them. No probing per request.

### 5.7 Cache and frozen copies

- The global cache key and the frozen-copy request digest are computed on the request as sent,
  so a reference request keys on the digest, not on the base64. This is cheaper than today
  (the research measured the key digest at 18.7 ms for an 8 MB inline body).
- A reference request and the inline request for the same file share one key (owner,
  2026-11-11; first decided on the PR #1450 request-key thread, 2026-10-23, and listed unfiled on
  `OME-1681`). Key material replaces each media part, inline or reference, with its media type
  and the SHA-256 of its decoded bytes. Hashing an inline payload's decoded bytes is cheaper than
  hashing it inside the canonical JSON today.
- This is a `KEY_REVISION` bump. It abandons every stored cache entry whose request has a media
  part, and frozen copies of picture runs captured before it stop replaying (accepted, owner,
  2026-11-11). Text-only entries keep their keys only if the builder can keep their key material
  byte-identical; otherwise the bump abandons them too, and the unit says so.
- A frozen-copy entry stores the request in reference form, with no grant. Replay is served from
  the copy and never resolves the reference, so a swept blob does not break replay.

### 5.8 Errors

| Code | Where | Permanent | When |
| --- | --- | --- | --- |
| `unsupported_content_part` (existing, 422) | gateway | yes | reference part with no blob source configured, or malformed |
| `x.blob_grant_invalid` (new, 403) | engine App, reported by gateway | yes | grant expired, forged, or does not cover the digest |
| `source_not_found` (existing) | engine App | yes | blob not in the grant's scope, or swept |
| `x.blob_digest_mismatch` (existing in engine and url4, new in gateway) | gateway | yes | fetched bytes do not match the digest or `x_size` |
| `request_too_large` (existing, 413) | gateway | yes | resolved attachments larger than the whole byte budget |
| `blob_source_unavailable` (new, 503) | gateway | no | blob source unreachable; retried like other transient upstream failures |

No error or log carries file bytes, the grant, the run id or the tenant's email.

## 6. Decided

- Scope: engine and gateway (owner, 2026-11-11).
- Target: about 20 MB per run, inline to providers; no provider uploads (owner, 2026-11-11).
- The gateway gets bytes by fetching from the engine with a grant, not by reading the bucket
  (owner, 2026-11-11). Tenant and run authorization stays in the engine.
- The url4 cap first drops to about 6,000,000 bytes in a separate fix (owner, 2026-11-11).
- Benchmark Case pictures stay inline; only url4 attachments go by reference.
- The cap follows the path: 20 MB by reference, about 6 MB inline.
- Inline and reference media share one cache key; the `KEY_REVISION` bump and the loss of old
  picture frozen copies are accepted.

## 7. Left to the builder

- Grant construction (AEAD token or opaque handle), within 5.3's constraints.
- The exact field names of the reference part (5.2).
- The base64 cache's size and eviction details, and the byte budget's value with its pod limit
  (5.5).
- How the S3 backend writes large blobs (single PUT or multipart).
- How the work splits into units. Suggested: (a) blob store chunked read/write and write-through;
  (b) App grant credential and streamed GET; (c) gateway reference parts, resolution, byte
  budget and the media cache key; (d) engine reference parts, grant minting and inline fallback;
  (e) the cap that follows the path. Each lands alone;
  (e) lands last.

## 8. Prerequisite to check

- Network: whether the hosted gateway can reach the engine App, and over which address. Today
  only the engine calls the gateway. The gateway unit (c) starts by checking the charts and the
  cluster layout; if the gateway cannot reach the App, that unit stops and comes back to the
  owner before any code (owner, 2026-11-11).

## 9. Acceptance

- The research benchmark re-run on the implementation, one 7.9 MB picture, 20 parallel calls:
  engine peak below 40 MB, longest event-loop stall below 50 ms.
- Gateway, same load: memory for waiting requests independent of file size; peak within the
  byte budget plus process baseline.
- A run with 20,000,000 bytes of attachments completes against a deployed gateway.
- Tests: a forged, expired or wrong-scope grant reads nothing; a digest not in the grant reads
  nothing; a grant never appears in a stored cache entry, frozen copy or log line; a reference
  never makes the gateway dial anything but its configured source; the inline path is
  byte-identical to today for callers that send `data:` URIs.

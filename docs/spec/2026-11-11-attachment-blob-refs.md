# Attachments by blob reference, engine to gateway

Status: draft, 2026-11-11. Owner: Sergey Bershadsky. Evidence: the research doc
"Attachment memory cost: proof and storage options"
(https://claude.ai/artifact/USXsTTKz3VuEdjpGoyZr6k), measured on 2026-11-11.

**Amended 2026-11-26 ([OME-1970](https://linear.app/openmined/issue/OME-1970/check-every-case-against-the-hosts-size-floor-when-it-is-sealed-and),
decisions 2, 3, 4 and 10).** The gateway cannot reach the engine App (8 below), so the grant and
the gateway's fetch (old 5.3 and 5.4) are replaced by an upload: the engine sends each file to
the gateway once per run, and the gateway keeps it in memory under the caller and the run's token.
Benchmark Case files now go by reference too, and the cache key stays today's (5.7). The amended
sections say so where they changed.

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
gateway's 8 MiB body cap. This spec is what lets it rise again. (Superseded 2026-11-15: the
inline cap is 8,000,000 bytes (PR #1588) and the gateway's default body cap rose to 12 MiB to fit
it, per HupBaHa's review of 2026-11-13.)

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
- Changing how SDK users or other callers send pictures to the gateway directly. Inline `data:`
  URIs stay supported, unchanged.
- Streaming the gateway's upstream request body. LiteLLM and the provider plugins build their
  bodies in memory; G3 accepts one body per upstream call.

## 4. Anti-goals: this fails even if it works when

- The gateway can be made to dial an address a caller chooses. `media_intake.py`'s invariant
  stands: a caller never picks what the gateway fetches.
- A log line or an error carries the run id (it is the run's bearer capability), the run token
  (5.4), the tenant's email, or file bytes.
- A digest alone authorizes a read. A digest is guessable whenever the content is.
- A file uploaded by one run is used by another run.
- The inline path regresses for callers that do not use references.

## 5. Design

### 5.1 Overview

1. Every url4 attachment of an engine run lands in the run blob store (OME-1540) before the
   first model call: blobs uploaded with `PUT /blob/sha256/{digest}` are already there, and
   `https://` attachment sources are written through as they are fetched (new).
2. The engine sends each attachment to the gateway as a blob reference part, never as base64,
   when the gateway is configured to accept references (5.6).
3. (Amended 2026-11-26.) Before the run's first model call, the engine uploads each file the run
   references to the gateway, once, with the run's token (5.3, 5.4). Every request of the run
   carries the same token.
4. The gateway checks the request shape and the token's scope, runs the cache lookup (5.7), and
   waits for its upstream slot holding only the small JSON.
5. Inside the slot, just before dispatch, the gateway resolves each reference from its own
   memory, fetching nothing, and builds the provider body as today. A file it no longer holds is
   answered "unknown file" before any upstream spend; the engine uploads it again and repeats
   the call.

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
- `x_size` is the decoded size. The gateway uses it for admission (5.5) before resolving, and
  refuses the request if the stored file's size differs (amended 2026-11-26: the gateway reads
  the file from its own store, 5.4, not from a fetch).
- Names prefixed `x_` are a placeholder for the builder to settle with the gateway's part
  parser; the fields themselves are the contract.

### 5.3 The upload (engine to gateway)

(Amended 2026-11-26, replacing the grant. The gateway's namespace allows egress only to DNS, its
database, model providers and tracing, and the engine App accepts calls only from its own
platform callers, so the gateway can never read from the App. The engine already calls the
gateway on port 9105, so an upload needs no new network rule, no grant and no new secret.)

- `PUT /v1/blobs/sha256/<64 lowercase hex>` on the gateway, the body the file's raw bytes, with
  the run's token in `X-AIGW-Run-Token` (5.4). The path spells the file the way the reference
  does (`blob:sha256/<hex>`). The answer is 201 with the reference, the type and the size, which
  the engine copies into the reference part's `x_media_type` and `x_size` (5.2).
- The route is outside the gateway's 12 MiB body cap and has its own: 15,000,000 bytes per file,
  the PDF floor (Bedrock refuses a PDF over about 20,000,000 bytes of base64, measured on 24 and
  26 Nov 2026; OME-1970 decision 4). A declared length over it is refused before reading; a body
  that crosses it is refused on the crossing chunk, which is never kept.
- The gateway reads the body as a stream, computing SHA-256 and size as it reads, and refuses a
  digest mismatch. It stores only png, jpeg, gif, webp and pdf, recognised by the file's leading
  bytes, with the same signatures as the engine's run blob store.
- Uploading a file the run already stored is accepted and replaces it, so the engine's retry
  after "unknown file" never fails on a file still held.
- The engine uploads each file once per run, keeping the set of digests it has sent, and hashes
  each file once when the Case is loaded, not per call.

### 5.4 The run token and the file store (gateway)

(Amended 2026-11-26, replacing the blob reads.)

- The gateway believes `X-User-Email` from every pod that can reach port 9105, and the Runner,
  which executes a Benchmark's scorer code, is one of them. So a caller identity is not enough:
  the engine mints a random **run token** per run (`secrets.token_urlsafe(32)`), sends it with
  each upload and each model call, and never logs it.
- The gateway stores each file under its **scope**, the caller's account id plus the SHA-256 of
  the token, and the file's digest. A lookup with another run's token, another caller's identity
  or no token finds nothing; the request then gets "unknown file", cached answer or not. The
  scope check runs before the cache lookup.
- The store holds each file's base64 text once per scope, in memory only, never on disk. It is
  bounded in bytes (`AIGW_BLOB_STORE_MAX_BYTES`, 40,000,000 by default, provisional until a Linux
  gateway pod's idle memory is measured) and drops the least recently used file first.
- A scope lives `AIGW_BLOB_SCOPE_TTL_SECONDS` after its first upload (58,800 s by default: the
  engine's 16 h run deadline plus the hour its run capability allows for queueing), then every
  file under it is dropped.
- A restart, a file dropped for room, or a second gateway pod that never got the file all read
  as "unknown file"; the engine uploads again (one extra upload per pod).

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
- `AIGW_MAX_REQUEST_BYTES` (12 MiB) applies to the body the caller sends. A reference request is a
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
  at 20,000,000 bytes; a run on the inline path keeps the lower cap (8,000,000 bytes, PR #1588)
  that fits the gateway's 12 MiB body cap (8,000,000 in base64 is 10,666,668 bytes). url4's run
  admission takes the cap from the engine, which knows its path from configuration before the run
  starts. The reference path does not change the gateway's body cap.
- Configuration is explicit: the engine sends references only when its gateway config says the
  gateway accepts them. No probing per request.

### 5.7 Cache and frozen copies

(Amended 2026-11-26, OME-1970 decision 2: the key stays today's.)

- Both stores key a request by the SHA-256 of its canonical JSON with the file's base64 inside:
  the gateway's response cache and the frozen copy a published run is replayed from. Changing
  what goes into that JSON would stop every stored picture entry from matching, so the response
  cache would pay again and a pinned replay would be refused.
- So the key stays today's. For a request carrying a reference, the gateway hashes the same bytes
  an inline request carries: the JSON before the file, then the stored file as its `data:` URI,
  then the JSON after, streamed into the hash without building the whole string. A reference
  request and the inline request for the same file share one key, and there is no `KEY_REVISION`
  bump; no stored entry or frozen copy is abandoned.
- The gateway hashes the whole file again on every call that references it, about 45 ms for an
  18 MB PDF (extrapolated from 18.7 ms for 8 MB, not measured), off the event loop. Accepted so
  that no cached answer is lost.
- A frozen-copy entry stores the request in reference form, with no token. Replay is served from
  the copy and never resolves the reference, so a dropped file does not break replay.

### 5.8 Errors

| Code | Where | Permanent | When |
| --- | --- | --- | --- |
| `unsupported_content_part` (existing, 422) | gateway | yes | reference part malformed |
| `invalid_request` (existing, 400) | gateway upload | yes | malformed digest in the path, or no usable run token |
| `blob_digest_mismatch` (new, 422) | gateway upload | yes | uploaded bytes do not hash to the digest in the path |
| `blob_too_large` (new, 413) | gateway upload | yes | file over 15,000,000 bytes |
| `blob_unsupported_media_type` (new, 415) | gateway upload | yes | leading bytes are none of png, jpeg, gif, webp, pdf |
| `x.blob_unknown` (new, engine) | engine, from the gateway's "unknown file" answer (its gateway code is named with the reference parts, OME-1970 PR 5) | no | the gateway does not hold the file for this run's scope; the engine uploads again (OME-1970 PR 8) |
| `request_too_large` (existing, 413) | gateway | yes | resolved attachments larger than the whole byte budget |

(Amended 2026-11-26.) The grant codes are gone with the grant. The gateway spells its codes as
plain identifiers, `blob_digest_mismatch` rather than url4's `x.blob_digest_mismatch`, because
every code it writes is declared in its code list, which admits only `[a-z][a-z0-9_]*` (gateway
code provenance, `docs/spec/2026-11-23-gateway-code-provenance.md`); the engine maps them.

No error or log carries file bytes, the run token, the run id or the tenant's email.

## 6. Decided

- Scope: engine and gateway (owner, 2026-11-11).
- Target: about 20 MB per run, inline to providers; no provider uploads (owner, 2026-11-11).
- The gateway gets bytes by an upload from the engine, once per run, stored under the caller
  and the run's token (owner, 2026-11-26, OME-1970 decisions 3 and 4; replaces the grant and the
  fetch of 2026-11-11, because the gateway cannot reach the App).
- The url4 cap first drops to about 6,000,000 bytes in a separate fix (owner, 2026-11-11;
  superseded 2026-11-15 — the gateway cap rose to 12 MiB instead and url4 stays at 8,000,000).
- Benchmark Case files go by reference too (owner, 2026-11-25, OME-1970; replaces "Case
  pictures stay inline").
- The cap follows the path: 20 MB by reference, 8,000,000 bytes inline.
- Inline and reference media share one cache key, and it is today's key: no `KEY_REVISION`
  bump, no stored entry or frozen copy lost (owner, 2026-11-26, OME-1970 decision 2).

## 7. Left to the builder

- The exact field names of the reference part (5.2).
- The byte budget's value with its pod limit, and the file store's final size, both from a Linux
  measurement of the gateway pod's idle memory (5.4, 5.5).
- How the S3 backend writes large blobs (single PUT or multipart).
- How the work splits into units. Suggested: (a) blob store chunked read/write and write-through;
  (b) the gateway upload route and file store (amended 2026-11-26); (c) gateway reference parts,
  resolution, byte budget and today's cache key over a reference; (d) engine uploads, reference
  parts, the run token and inline fallback;
  (e) the cap that follows the path. Each lands alone;
  (e) lands last.

## 8. Prerequisite to check

- Network: whether the hosted gateway can reach the engine App, and over which address. Today
  only the engine calls the gateway. The gateway unit (c) starts by checking the charts and the
  cluster layout; if the gateway cannot reach the App, that unit stops and comes back to the
  owner before any code (owner, 2026-11-11).
- Checked 2026-11-26 (OME-1970): it cannot. The gateway's network rules allow egress only to
  DNS, its database, model providers and tracing, and the App accepts calls only from its own
  platform callers. Hence the upload design in 5.3 and 5.4.

## 9. Acceptance

- The research benchmark re-run on the implementation, one 7.9 MB picture, 20 parallel calls:
  engine peak below 40 MB, longest event-loop stall below 50 ms.
- Gateway, same load: memory for waiting requests independent of file size; peak within the
  byte budget plus process baseline.
- A run with 20,000,000 bytes of attachments completes against a deployed gateway.
- Tests: another run's token, another caller or no token reads nothing; an expired scope reads
  nothing; a run token never appears in a stored cache entry, frozen copy or log line; a
  reference never makes the gateway dial anything; an uploaded file is never written to disk;
  the inline path is byte-identical to today for callers that send `data:` URIs.

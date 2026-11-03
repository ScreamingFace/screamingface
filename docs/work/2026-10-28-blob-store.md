---
ticket: OME-1540
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-28
finished: 2026-10-28
---

# blob-store — run-scoped, content-addressed blob store with upload and fetch routes

## Intent

Give the engine a place to keep a file that has no URL (a client upload, an https attachment
written through by `OME-1543`), so url4 `/blob/sha256/<hex>` (C1) and `blob:sha256/<hex>` (C3)
refs resolve as a direct tenant + run store read (spec
`docs/spec/2026-10-16-OME-1535-file-input-execution.md` F1, F3, §4). Linear `OME-1540`.

## Owner decisions (Sergey, 2026-10-28)

- **Q1(a) auth + run binding:** `PUT /blob/sha256/<hex>` and `GET /blob/sha256/<hex>` both need
  `URL4-Capability`; a blob is stored under the token's topic (`sub` = the run). A digest from
  another topic → 404 `source_not_found`.
- **Q2(a) tenant:** the verified `X-User-Email`, or the fixed partition `anonymous` when absent.
  Key = (tenant, topic); every read must match both.
- **Q3(a) route shape:** client-stated digest in the path; ingest mismatch → 422
  `x.blob_digest_mismatch`; idempotent 201 (new) / 200 (already held); body
  `{ref, sha256, size_bytes, media_type}`.
- **Q4(a) limits + retention:** 8,000,000 B per blob → 413 `x.blob_too_large`; the five
  attachment types (png, jpeg, gif, webp, pdf) only → 415 `x.blob_unsupported_media_type`;
  both in `Settings`. Retention = the existing artifact TTL sweep, under a `blobs/` prefix
  (S3: the bucket lifecycle rule, as for artifacts).
- Reuse the filesystem/S3 artifact store, no new dependency; sha256 verified on upload and on
  every read (read mismatch → 500 `x.blob_digest_mismatch`, logged as store corruption); logs
  carry digest + size only.
- **Wire sign-off pending:** `x.blob_too_large` and `x.blob_unsupported_media_type` are new
  `x.*` codes and need Kevin's url4 wire sign-off, like the spec's other proposed codes.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/artifacts/blobs.py` — `BlobScope`,
  `StoredBlob`, `BlobPolicy`, `BlobStore` (ingest/read/sweep), typed errors, filesystem + S3
  object backends, `ScopedBlobReader` (async `read("sha256:<hex>")`, the `OME-1545` port shape).
- `artifacts/s3.py` — keyed `put_object` / `get_object` on the existing signed client.
- `artifacts/wiring.py` — `blob_store_from_env` + `blob_scope_from_env` for the run half.
- `rest/blobs.py` — the two routes; `rest/__init__.py` + `app.py` — wiring and the TTL sweep.
- `config.py` — `blob_max_bytes`, `blob_media_types`.

## Test plan

- Store: round trip on filesystem and fake-S3 backends; idempotent re-ingest; ingest digest
  mismatch; oversize; disallowed / parameterised media type; unknown digest → None; other run /
  other tenant → None; read-side corruption → typed mismatch + corruption log without bytes;
  traversal-shaped digest refused; sweep ages out blobs only under `blobs/`.
- Reader adapter: `sha256:<hex>` read, wrong prefix → None, scoped.
- Routes: 401 without token; PUT 201 then 200; 422 / 413 / 415 problems with codes; GET bytes +
  media type; 404 `source_not_found` for unknown / other topic / other tenant; 500 on corruption.

## Acceptance

- The OME-1540 acceptance list, minus the https write-through itself (that is `OME-1543`; this
  unit gives it the ingest call it writes through with).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `rest/__init__.py` (router export) and
  `schemas/openapi.py` (the declared `Blobs` tag the docs gate requires). New tests:
  `tests/unit/test_blob_store.py`, `test_blob_routes.py`, `test_blob_wiring.py` (90 tests).
- **Commits:** see branch `blob-store` (single `feat(engine)` commit).
- **Gates:** `run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN
  (append-only, ruff, format, pyright, layering, pytest 95.8% total coverage).
- **Deviations:**
  - `app.py`: the storage wiring moved into `_install_storage` and the blob sweep into
    `_sweep_blobs` to stay within ruff's statement/complexity limits; behaviour unchanged.
  - The Runner gets `blob_reader_from_env` (a `ScopedBlobReader`, the OME-1545 port shape) but
    is not bound into the run path here: `bound_blob_reader` lives on #1588, which this unit
    must not touch. Binding it is a one-liner once #1588 lands.
  - `ScopedBlobReader` raises `BlobDigestMismatch` (code `x.blob_digest_mismatch`) on store
    corruption instead of returning bytes; #1588's `_verified_body` only maps its own
    `AttachmentPartError`, so its integration must map this one too.
  - Residuals: upload is capped per blob, not per run (the per-run 20-file / 8,000,000-byte
    caps are `OME-1543`'s); S3 retention depends on the bucket lifecycle rule covering `blobs/`.

## Review round 1 — Khoa's 5 inline comments on #1603 (2026-11-02), owner decisions 2026-11-03

status: blocked (items 2-5 done; item 1 stopped on a design fork, see Outcome)

- **Planned:**
  1. `rest/blobs.py:107` total upload limit → a separate blob storage backend (`blobs.storage`
     config + chart). See Outcome for whether it landed.
  2. `rest/blobs.py:117` storage failures → 503 problem+json with `Retry-After`
     (`S3StorageError`, `OSError`) on both PUT and GET.
  3. `artifacts/blobs.py:209` → the Helm README Expiry section names `blobs/` with a
     lifecycle-rule example.
  4. `config.py:135` → `blob_media_types` must be a subset of `ATTACHMENT_MEDIA_TYPES`, refused
     at config load.
  5. `rest/blobs.py:157` → `Cache-Control: private, no-store` on blob responses; magic-byte
     check at ingest (App policy), mismatch → 415 `x.blob_unsupported_media_type`.
- **Test plan:** new file `tests/unit/test_blob_review_hardening.py` only (prior tests
  append-only): 503 + Retry-After for `S3StorageError` and `OSError` on PUT and GET; config
  refusal for `text/html` / `image/svg+xml`, case-normalized subset accepted; Cache-Control on
  200 and on problems; signature match accepted and mismatch refused for all five types; the
  signature table covers exactly `ATTACHMENT_MEDIA_TYPES`.

### Outcome (review round 1)

- **Done:** items 2, 3, 4, 5.
  - `rest/blobs.py`: `S3StorageError` / `OSError` on PUT or GET → 503 problem+json,
    `Retry-After: 5` (`BLOB_STORAGE_RETRY_AFTER_S`, same WHY as the run queue's broker-down
    value), `permanent: false`, backend message never echoed, a WARNING log naming only the
    operation and the exception type. Every GET answer carries `Cache-Control: private,
    no-store`.
  - `artifacts/blobs.py`: `MEDIA_TYPE_SIGNATURES` (PDF, PNG, JPEG, GIF87a/89a, WebP RIFF+WEBP)
    and `BlobPolicy.verify_signature`; a mismatch raises `BlobContentMismatch`, a subclass of
    `BlobUnsupportedMediaType` → 415 `x.blob_unsupported_media_type` (no new wire code).
    `app._build_blob_store` turns verification on. All five attachment types have a reliable
    signature; the table's keys are pinned to `ATTACHMENT_MEDIA_TYPES` by a test, and the WHY
    anchor says a type without one needs its own decision.
  - `config.py`: `blob_media_types` validator — subset of `ATTACHMENT_MEDIA_TYPES`, normalized,
    error names the refused types and the allowed set.
  - Helm `README.md` Expiry: `blobs/` documented with a lifecycle-rule example.
- **Tests:** new `tests/unit/test_blob_review_hardening.py` (40 tests); no prior test touched.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` ALL GREEN; `helm lint` +
  `verify_chart_wiring.py` (121/121) green.
- **Deviations:** `verify_signature` defaults to False on `BlobPolicy` (the App sets True)
  because a prior store test re-ingests PNG bytes labelled `image/jpeg` and a wiring test uses
  a short non-PNG body; default-on would have changed prior tests.
- **Stopped — item 1 (separate blob storage backend):** the port is not the fork
  (`BlobObjects` already is the blob port, with filesystem and S3 adapters); the S3/chart
  provisioning is. The bundled Garage creates exactly one bucket (`--default-bucket`) and the
  chart deliberately has no bootstrap hook, so a separate blob bucket cannot be created by the
  chart as it stands, and a second bucket on the same Garage volume does not isolate capacity
  anyway. Options reported to the owner; nothing for item 1 is committed.

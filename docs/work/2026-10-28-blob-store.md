---
ticket: unfiled   # Linear OME-1540 exists (parent tracker OME-1681, epic OME-1529); backfill at PR-open
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

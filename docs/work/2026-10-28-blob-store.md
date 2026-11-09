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

status: done (items 2-5 in 5b23a101a; item 1 after the owner chose option A, see below)

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

### Review round 1, item 1: separate blob storage (owner decision 2026-11-03, option A)

status: done (unblocked by owner decisions Q1(a) / Q2(a), 2026-11-03)

- **Built:** `job_env.BLOB_*` names;
  `Settings.blob_store` / `blobs_dir` / `blob_s3_*`; `artifacts.wiring.blob_objects_from_values`
  (both halves) + `blob_s3_config_from_values` (never borrows the artifact settings); App refuses
  `runner=queue` with a filesystem blob store; chart `blobs.storage` values + schema, a second
  bundled Garage (`garage-blobs.yaml`, own PVC 5Gi, own `<fullname>-blob-storage` Secret, component
  `garage-blobs`), blob keys in both ConfigMaps, the blob Secret on both workloads; README
  "Blob storage" section and per-bucket lifecycle text; verifier block (15 new checks).
- **Tests:** `test_blob_storage_isolation.py` (21), `test_blob_storage_chart_contract.py`.
  Written after the code in this item (TDD order deviation).
- **Stopped on:**
  - `test_catalog_wiring.py::test_no_setting_holds_an_aigateway_credential` pins the set of
    secret-shaped `Settings` fields; `blob_s3_access_key` / `blob_s3_secret_key` must be added
    to it with a reviewed rationale.
  - `test_chart_render_garage_selector.py` (2 tests) assumes ONE Garage (`next(... "garage" in
    name)`; every "garage" Service must select that Garage's pods); with two Garages it picks
    the blob one.
- **Kept as-is (follow mode):** with `URL4_CLOUD_BLOB_STORE` unset the blob store follows the
  artifact directory/bucket, because `test_blob_routes.py::test_the_artifact_startup_sweep_also_
  ages_out_blobs` and `test_blob_wiring.py` pin that location. The chart always sets it.
- **Unblocked (owner, 2026-11-03):** Q1(a) — `test_catalog_wiring.py` pinned set gains
  `blob_s3_access_key` / `blob_s3_secret_key` with a reviewed rationale; Q2(a) —
  `test_chart_render_garage_selector.py` picks the results Garage by exact name and asserts each
  Garage Service selects only its own pods. Both recorded in
  `.claude/test-change-approvals/OME-1540.json` (approver Sergey Bershadsky, base/approved blobs).
- **Security review fix:** the blob Garage's `rpc_secret` is a random 64-hex value in
  `<fullname>-blob-storage` (`GARAGE_RPC_SECRET`, reused across upgrades by `lookup`), fed to
  Garage by env (supported since Garage v0.8.2, per the Garage configuration reference); its
  config carries no derived constant. The App and the pool now read the blob key pair by named
  `secretKeyRef`, so the RPC secret reaches the Garage pod only. Verifier checks: no `rpc_secret`
  line in the blob Garage config, two releases get different RPC secrets.
  Residual (not changed, owner to decide): the results `garage.yaml` still derives its
  `rpc_secret` with `derivePassword` from the release name and a constant master.
- **Deploy prerequisite:** the hosted platform NetworkPolicies (outside this repo) must admit
  `component: garage-blobs` on 3900 (and 3901 if listed) — in the PR body.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` ALL GREEN (two approved
  test transitions), `helm lint` green, `verify_chart_wiring.py` 140/140.

## Review round 2 — HupBaHa CHANGES_REQUESTED on head 8f47715c9 (owner decisions 2026-11-04)

status: done (item 1 unblocked by owner approval 2026-11-04)

- **Intent:** close the three storage/security blockers, the two deployment blockers and the
  concurrent-first-upload race from Dmitry's review.
- **Owner decisions (Sergey, 2026-11-04):** (1) unset blob store → fail closed, follow mode
  removed; (2) backend reads bounded at `max_bytes + 1`, S3 streamed, a small sidecar cap;
  (3) closed sidecar schema → permanent typed corruption with `private, no-store`; (4) Helm:
  external S3 with no credentials and no `existingSecret` fails render, App gets
  `checksum/blob-secret`; (5) atomic first write so exactly one request returns 201.
- **Planned changes:** `artifacts/blobs.py` (bounded reads, closed sidecar, atomic create,
  `BlobCorrupted`), `artifacts/s3.py` (streamed capped GET, conditional PUT),
  `artifacts/wiring.py` (no follow mode), `app.py`, Helm `deployment.yaml`, `_helpers.tpl` /
  `secret-blob-storage.yaml`, `verify_chart_wiring.py`.
- **Test plan:** new `tests/unit/test_blob_review_round2.py` — oversize data / sidecar on both
  backends is typed corruption; S3 read never calls `.content` past the cap; sidecar with
  extra key, wrong type, wrong size, `text/html`, truncated JSON → 500 `x.blob_digest_mismatch`
  + `private, no-store`; signature checked on read; two concurrent first uploads → one 201;
  S3 PUT of the sidecar carries `If-None-Match: *` and a 412 means "already held".
- **Acceptance:** all of the above green; gates, `helm lint`, chart verifier green.

### Outcome (review round 2) — BLOCKED on item 1

- **Built (uncommitted, gates green vs merge-base 107de3281):** items 2, 3, 5 in
  `artifacts/blobs.py` (`BoundedBlobObjects` port with `get_at_most` / `create`,
  `_UnboundedObjects` adapter for put/get-only backends, `BlobCorrupted(BlobDigestMismatch)`,
  `SIDECAR_MAX_BYTES = 1024`, closed sidecar schema, size + signature checked on read, corrupt
  sidecar healed by a verified re-upload, create-exclusive first record) and `artifacts/s3.py`
  (`get_object_at_most` streamed + capped, `put_object_if_absent` with signed
  `If-None-Match: *`, `S3ObjectTooLarge`; the unbounded `get_object` removed); `rest/blobs.py`
  maps ingest-side corruption to 500. Item 4: render fails for an external blob endpoint
  without `existingSecret` or a full key pair; App pod carries `checksum/blob-secret`.
  Tests: `test_blob_review_round2.py` (45 cases); verifier +4 checks (144/144).
- **Garage probe (2026-11-04, dxflrs/garage:v2.3.0 in docker):** a conditional
  `If-None-Match: *` PUT on an existing key answered 200 and overwrote — Garage ignores the
  condition. Documented in `S3ArtifactStore.put_object_if_absent` and the Helm README.
- **Stopped on item 1 (fail closed):** removing follow mode changes prior tests.
  Startup failure breaks every `create_app` test without a blob store (hundreds). A typed 503
  breaks 24 cases in 3 files: `test_blob_routes.py` (12, fixture `_app` sets no blob store; one,
  `test_the_artifact_startup_sweep_also_ages_out_blobs`, pins blobs under `artifacts_dir`),
  `test_blob_review_hardening.py` (7, same fixture), `test_blob_wiring.py` (3, env has no
  `BLOB_STORE`; `test_s3_selection_builds_the_s3_backend` asserts the follow-the-artifact-bucket
  behaviour itself).
- **Also flag:** the verifier's existing check "an operator's own blob endpoint replaces the
  bundled blob Garage" now renders with `existingSecret` set (its assertion unchanged), because
  the item-4 fail refuses its old credential-less input.
- **Main moved** (33 commits, none touching this branch's files); `run_gates --base origin/main`
  reports main's own test changes until merged.

### Review round 2, item 1: fail closed (owner approval 2026-11-04)

- **Decision:** typed 503 from the blob routes — the engine's shape for an unconfigured optional
  dependency (`rest.catalog`, `rest.cache_entries`); startup failure would have broken every
  App built without a blob store. `artifacts.wiring.blob_objects_from_values` raises
  `BlobStoreNotConfigured` when `URL4_CLOUD_BLOB_STORE` is unset/blank (follow mode deleted);
  `create_app` logs it and leaves `app.state.blob_store = None`; `rest.blobs._store` answers
  503 problem, `permanent: true`, no `Retry-After`, `private, no-store`; the Runner's
  `blob_reader_from_env` raises `BlobStoreNotConfigured`.
- **Tests:** 9 new cases in `test_blob_review_round2.py` (written after the code — TDD order
  deviation). Approved prior-test changes recorded in
  `.claude/test-change-approvals/OME-1540.json` `amendments[0]`: the two `_app` fixtures
  (`blobs_dir` = the same tmp dir, so `test_corrupted_stored_bytes_are_500_digest_mismatch` and
  the startup-sweep test needed no edit), `test_blob_wiring.py` `_env` + the s3 selection test
  (asserts the separate blob bucket), the verifier's external-endpoint render
  (`existingSecret`).

## Review round 3 — HupBaHa CHANGES_REQUESTED on head 9b2dbadec (2026-11-04)

- **Intent:** close the two blockers and the low-risk follow-ups. Status: DONE.
- **Planned changes:** (1) `artifacts/s3.py` — every error body on a streamed path (sync
  `get_object_at_most`, async `_stream`) reads at most a 512-byte diagnostic prefix;
  (2) `BlobStore.ingest` — a stored record that disagrees with the verified upload (size, type,
  or the signature of its recorded type) is corrupt and rewritten, `created=False`;
  (3) Helm — whitespace-only inline blob S3 keys fail the render (`trim`), verifier check;
  (4) split `artifacts/blobs.py` (589 lines) into focused modules, `blobs` re-exports every
  name; (5) Garage `If-None-Match` — documented limitation, no code.
- **Test plan:** append-only tests in a new `test_blob_review_round3.py`: lazy 1 MB HTTP 500 with
  `max_bytes=100` pulls ≤ prefix + one chunk (sync and async); PDF bytes under a closed
  `image/png` sidecar healed by a valid `application/pdf` re-upload; verifier check for blank
  keys. No prior test changes.
- **Acceptance:** engine gates green vs origin/main, helm lint, verifier green.

### Outcome (review round 3)

- **Merged origin/main** (ecb21ce4a, `feat(url4): resolve blob file refs`), no conflicts.
- **Items 1-2 — c3140bc42.** `s3.py`: `get_object_at_most` and `_stream` read a 512-byte
  error prefix (`iter_bytes`/`aiter_bytes`, first chunk only), decode `errors="replace"`,
  close; `_stream`'s error now carries the 200-char detail too. `_request`
  (HEAD/PUT/DELETE) was left buffering in c3140bc42 and fixed in the follow-up below. `blobs.py`: `_existing` keeps a record only if the bytes carry its recorded
  type's signature (with `verify_signature`); a corrupt record is rewritten, `created=False`
  (also for an unparseable sidecar, which used to return `created=True`).
- **Item 3 — 33579f98d.** `secret-blob-storage.yaml` trims the inline keys; verifier 145/145.
- **Item 4 — 89f099168.** `blob_schema.py` 216, `blob_objects.py` 195, `blobs.py` 287 lines.
- **Item 5:** no code — the Garage `If-None-Match` limitation stays documented.
- **Tests:** `test_blob_review_round3.py` (12 cases, written first, RED confirmed). No prior test
  changed.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` ALL GREEN; helm lint OK.
- **Deviation:** item 2 is checked by signature, not by equality with the new label: equality
  would break `test_a_repeat_upload_keeps_the_first_media_type` (label-trusting store, no
  signature check). With `verify_signature` (the App) the two are the same test.
- **Follow-up (coordinator, same round):** `_request` now uses `client.stream`, so HEAD/PUT/DELETE
  error bodies cost the same 512-byte prefix; 404/412 unchanged and never read. 5 new tests
  (RED confirmed), no prior test changed.

## Review round 4 — HupBaHa CHANGES_REQUESTED on head ff9ddd58d (2026-11-04)

status: done

- **Finding:** `iter_bytes`/`aiter_bytes` decode `Content-Encoding` before chunking (httpx
  0.28.1), so a 19 KB gzip body inflating to 20 MB peaked near 50 MB under a 100-byte cap. This
  affected the capped success read, the sync error diagnostics and the async artifact stream.
- **Fix:** `s3.py` reads object bytes and error prefixes with `iter_raw`/`aiter_raw`, through
  the `_raw_chunks`/`_araw_chunks` helpers. A pre-read in-memory response is sliced instead,
  because `iter_raw` raises `StreamConsumed` on it. A non-identity `Content-Encoding` is never
  decoded. On a 2xx (capped GET, artifact stream) it is refused as `S3StorageError`. On an
  error response the body is left unread and the message says `<gzip-encoded body not read>`.
- **Tests:** `test_blob_review_round4.py` has 17 cases, written first, with RED confirmed
  (peaks of about 17 MB). gzip and deflate bombs inflate to 20 MB each. They run on the success
  read, the error read, the `_request` error, the blob backend, and the async stream success and
  error. Each asserts `S3StorageError` and a tracemalloc peak under 1 MB above baseline. Identity
  bodies are still read, both pre-read and streamed. No prior test changed.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` ALL GREEN; `s3.py` 445 lines.

### #1603 review — `blob_max_bytes` ceiling (khoaguin, 2026-11-05)

- **Finding:** `blob_max_bytes` had no ceiling, while the Runner's `blob_store_from_env` reads
  with the default policy (8,000,000). An App set to 10 MB would store a 9 MB PDF that the Runner
  then refuses as `x.blob_digest_mismatch`. The chart does not expose the setting.
- **Fix:** `config.py` sets `le=DEFAULT_BLOB_MAX_BYTES` on the field, so a larger cap is refused
  at config load.
- **Tests:** three cases appended to `test_blob_review_hardening.py`, written first with RED
  confirmed: 8,000,000 accepted, 8,000,001 refused, and the env var behaves the same. No prior
  test changed.

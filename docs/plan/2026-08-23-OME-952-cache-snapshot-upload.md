# OME-952 — aigateway cache-snapshot upload (plan)

Implements `docs/spec/2026-08-22-OME-951-admin-cache-snapshot-upload.md` (approved) — gateway half.

## Recon-derived decisions (beyond the spec)

- **Live-table ground truth (PG16)**: no DB-side defaults for `id`/`created_at`/`updated_at`;
  column order equals model-definition order; uniques: `id` pkey + `key_hash`. Therefore the
  merge INSERT generates ids with core `gen_random_uuid()` (never carries snapshot ids — kills
  the cross-deployment id-collision class) and sets `updated_at = now()` on both insert and
  update. Spec's illustrative SQL is extended with `updated_at`; intent unchanged.
- **COPY feeding**: `tortoise.backends.asyncpg` client exposes `acquire_connection()` → raw
  `asyncpg.Connection`; `copy_to_table(source=<async gen>, columns=<ours>)` sends bytes verbatim.
  The dump's COPY-header column list must match our canonical list EXACTLY (order included) —
  refusals otherwise; our identifiers (never upload-derived ones) reach the COPY command.
  The `\.` terminator is stripped by the slicer; asyncpg ends the stream with CopyDone.
- **Blocking gzip reads** happen in `asyncio.to_thread` chunk reads feeding the async generator.
- **Hexagonal**: core may not import the openrouter plugin. New core registry
  `core/request_cache/revisions.py`; the plugin registers its adapter revision at plugin load
  (plugins→core is the allowed direction; same wiring pattern as the provider registry).
- **Sync vs async validation**: busy-slot (409), dialect (400), multipart shape (422),
  content-length over cap (413) are synchronous HTTP errors. Everything else (checksum, row
  count, revision, no-copy-block, real size cap, replace guard) runs inside the job and lands
  as terminal state `refused` — the spec's contract.
- **python-multipart** added as a dependency (FastAPI multipart parsing).

## Files

- `config.py` — `cache_upload_max_bytes` (default 256 MiB, `AIGW_CACHE_UPLOAD_MAX_BYTES`).
- `core/request_cache/revisions.py` (new) — core-owned adapter-revision registry +
  `active_cache_revisions()` incl. `PARAMETER_CONTRACT_REVISION`.
- `plugins/openrouter_provider/global_cache.py` — one registration call at import.
- `core/request_cache/snapshot.py` (new) — pure parsing: COPY-header/columns parser, byte-level
  block slicer, gzip magic, `SnapshotManifest` model + strict validation.
- `core/request_cache/bulk_loader.py` (new) — `PostgresCacheSnapshotLoader`: staging
  create/truncate, asyncpg COPY load, single-transaction merge/replace with counters.
- `core/request_cache/upload_job.py` (new) — `CacheUploadRunner` (single in-flight slot,
  owned task, bounded history) + `CacheJobRecord`.
- `core/admin_schemas.py` — `AdminCacheInfoOut`, `AdminCacheJobOut`, `AdminCacheJobList`.
- `routes/admin_cache.py` (new) — 4 routes; `AdminAuditRoute`; `CurrentAdmin`.
- `main.py` — wire runner on `app.state.cache_upload_runner`; include router.
- `pyproject.toml` — `python-multipart`.

## Tests

- `tests/unit/test_cache_snapshot_slicing.py` — header parse (order variants, wrong table,
  no block, early EOF), terminator handling, escaped payload passthrough, gzip magic,
  manifest validation (schema tag, hex sha, row_count, revisions).
- `tests/unit/test_cache_upload_job_runner.py` — fake loader: full happy path with counters;
  refused paths (checksum, row-count, revision mismatch, `force` override recorded, replace
  guard with/without acknowledgement, size cap, no block); busy slot; failure state.
- `tests/unit/test_cache_upload_routes.py` — auth gates per the account-route pattern;
  409/400/413 sync refusals; job/job-list serialization via the stubbed runner.
- `tests/integration/test_cache_snapshot_upload_postgres.py` — testcontainers PG (pattern of
  `test_global_cache_store_postgres.py`): real dump fixture; COPY loads; merge keeps
  lifecycle columns, replaces content, byte-identical `response_json`; replace path; staging
  cleanup; concurrent single-slot. Marked `needs_postgres`.

## Gates

`uv run ruff check && uv run ruff format --check && uv run pyright && uv run python scripts/check_no_enterprise.py && uv run pytest --cov=aigateway --cov-fail-under=80 -q`

---
id: OME-952
linear_url: https://linear.app/openmined/issue/OME-952/aigateway-cache-snapshot-upload-routes-and-loader
status: todo
type: improvement
priority: 3
labels: [aigateway, autonomous, agentic]
created: 2026-08-22
closed:
---

# aigateway: cache-snapshot upload routes and loader

Gateway half of OME-951, per `docs/spec/2026-08-22-OME-951-admin-cache-snapshot-upload.md`:

- `GET /v1/admin/cache/info`, `POST /v1/admin/cache/snapshots`,
  `GET /v1/admin/cache/snapshots/jobs[/{id}]` behind `CurrentAdmin`, audited.
- Typed models in `core/admin_schemas.py` (`AdminCacheInfoOut`, `AdminCacheJobOut`, …) so the
  generated console client stays typed.
- Multipart spool-to-disk with a size cap; COPY-block slice; staging-table COPY load;
  single-transaction merge (`ON CONFLICT (key_hash) DO UPDATE`, content columns from the
  snapshot, local `id`/`created_at`/`hit_count`/`last_hit_at` survive); guarded replace.
- In-process async job runner on `app.state`; one load at a time (`409`); job records with
  states, counters, warnings.
- Revision guard against the manifest sidecar (OME-954): checksum, row count, revision
  constants; `force` override recorded on the job and audit line.
- Tests for every acceptance criterion in the spec (the admin routes currently have none —
  this unit adds the harness for them).

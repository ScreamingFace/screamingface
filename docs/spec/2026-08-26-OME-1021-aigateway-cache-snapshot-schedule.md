---
title: aigateway response-cache weekly snapshot to Garage
ticket: OME-1021
status: approved
date: 2026-08-26
approved: 2026-08-26
---

# AI Gateway response-cache weekly snapshot to Garage

## 1. Decision

aigateway exports its global response cache (`public.request_cache_entries`) to blob
storage **every Friday at 05:00 UTC**, in the exact snapshot format the gateway already
loads (OME-952), so a weekly archive is directly consumable by the existing admin upload
and `local-k8s restore-cache` — no new format, no restore automation.

The export runs **in-process** in the gateway's `_lifespan` (single replica today —
logged invariant, same as the Engine's orphan reaper). The gateway bundles its **own
Garage** instance (mirroring the Engine's proven self-configuring Garage chart) and PUTs
the snapshot + manifest there; an external S3-compatible endpoint remains available as an
override. Objects land in a **dedicated bucket** `screamingface-cache-snapshots` under a
`cache-snapshots/` prefix, so they can never collide with the Engine's artifact keys
(sha256 hex in `screamingface-artifacts`).

Locked decisions (owner-confirmed 2026-08-26):

1. **Garage wiring**: bundle a Garage StatefulSet in the aigateway chart, mirroring the
   Engine chart; external-endpoint override (`snapshot.storage.endpointUrl`).
2. **Catch-up**: none. The schedule is strictly "next Friday 05:00 UTC"; a gateway that
   was down at 05:00 skips that week (next Friday is the backstop).
3. **Retention**: keep everything. No in-app LIST/DELETE — the SigV4 slice stays
   PUT-only, mirroring the Engine's artifact-store invariant (expiry would be a bucket
   lifecycle rule, an operator decision).
4. **Trigger**: schedule only. No admin/manual export route in v1.

## 2. Context — what already exists

- **Format** (`core/request_cache/snapshot.py`, OME-952): a gzip'd single-table dump of
  `request_cache_entries` — fixed preamble, one `COPY public.request_cache_entries
  (<CANONICAL_COLUMNS>) FROM stdin;` line, COPY-text rows, `\.` terminator, fixed
  epilogue — plus a JSON sidecar `SnapshotManifest` (`screamingface.cache-snapshot.v1`:
  `schema`, `generated_at`, `row_count`, `sha256`, `revisions`).
- **Loader** (`core/request_cache/bulk_loader.py` + `admin_cache.py`): spools an upload,
  re-feeds the COPY block through asyncpg `copy_to_table` into a staging table, then
  MERGE/REPLACEs. `CopyBlockSource` works byte-level: it scans for the header line, yields
  rows verbatim, stops at `\.`.
- **Revision gate**: the manifest must carry `active_cache_revisions()` (the parameter
  contract constant + each provider adapter's projection revision). A snapshot built under
  different constants loads cleanly and never serves — the export must stamp them.
- **Garage precedent** (Engine): self-configuring Garage v2.3.0 StatefulSet
  (`--single-node --default-access-key --default-bucket`, keys adopted from a Secret),
  path-style addressing, hand-rolled SigV4 over httpx (`artifacts/sigv4.py`,
  `artifacts/s3.py`), deliberately PUT/GET-only. aigateway has no boto3; it mirrors this.
- **Export-side reference**: `draco-cache-seed-v4/make_pg_snapshot.py` already emits the
  exact byte contract from `rows.jsonl` (preamble, header, `copy_escape`-escaped rows,
  `\.`, epilogue, manifest) — the real export differs only in that the rows come from the
  live table via Postgres COPY instead of a JSONL file. Verified against the pinned
  asyncpg 0.31.0: `Connection.copy_from_query` wraps the query as `COPY (…) TO STDOUT`
  and awaits a coroutine sink per chunk (natural backpressure).

## 3. Requirements

Functional:
- Every Friday 05:00 UTC, export `request_cache_entries` to a `.sql.gz` + `.manifest.json`
  pair in Garage, in the OME-952 format, with correct `row_count`, `sha256` (of the gzip
  file) and `revisions` (`active_cache_revisions()`).
- Objects are named `cache-snapshots/<YYYY-MM-DD>T<HH-MM-SS>Z.sql.gz` and
  `…manifest.json` in bucket `screamingface-cache-snapshots` (both configurable).
- The export must not perturb the request path: dedicated DB connection, bounded memory,
  no event-loop blocking.
- Schedule failures retry (bounded backoff) and then fail loudly; the request path is
  never affected.

Non-functional:
- Batch problem: ~190k rows / ~40–80 MiB gzip per week, one run/week. ~5–10 GiB/yr on
  Garage's single-node store. Latency irrelevant; availability = "next Friday + logs".
- Single replica assumption (logged), matching the Engine's orphan reaper.

Out of scope:
- Restore automation (exists), retention/pruning (keep-all), manual trigger, metrics
  dashboard, multi-replica scheduling (advisory-lock/CronJob).

## 4. Design

### 4.1 Export — `core/request_cache/snapshot_export.py`

`CacheSnapshotExporter`:

1. Open a **dedicated `asyncpg` connection** (`asyncpg.connect(dsn)`) from the same
   `AIGATEWAY_DATABASE_URL`. NOT the shared Tortoise pool — a weekly COPY must never
   consume a request-path connection. Non-Postgres DSN → raise
   `SnapshotExportUnsupportedDatabase` (mirror of `CacheUploadUnsupportedDatabase`).
2. Stream `COPY (SELECT <CANONICAL_COLUMNS in column order> FROM request_cache_entries)
   TO STDOUT` via `Connection.copy_from_query(..., output=_sink)`.
3. `_sink(chunk)`: `await asyncio.to_thread(gz.write, chunk)` — gzip compression and disk
   I/O stay off the event loop. The raw file is wrapped in a hashing tee so the **sha256
   of the gzip bytes** is computed in-stream (the value the manifest must carry and the
   loader verifies against).
4. Write the byte contract ourselves: data-only preamble (mirror `make_pg_snapshot`),
   the exact `COPY public.request_cache_entries (<CANONICAL_COLUMNS>) FROM stdin;\n`
   header line, the streamed rows, then `\.\n` and the epilogue — all through `gz`.
5. `row_count` from `copy_from_query`'s status string (`'COPY <N>'`).
6. Build `SnapshotManifest` (`schema` = `screamingface.cache-snapshot.v1`,
   `generated_at` = UTC ISO 8601, `row_count`, `sha256`, `revisions =
   active_cache_revisions()`); write `<ts>.manifest.json` beside the archive.
7. PUT both objects to the store, then delete the spool files in `finally`.

Typed error hierarchy (`SnapshotExportError` subclasses: DB unreachable, COPY refused,
disk full/spool overflow, store refused, store unreachable). A `cache_snapshot_max_bytes`
cap (default 512 MiB) protects the spool dir; exceeding it fails the run loudly rather
than filling the pod disk.

### 4.2 Object store — `core/object_store.py` (+ `core/sigv4.py`)

`S3ObjectStore` mirroring the Engine's `artifacts/s3.py` + `artifacts/sigv4.py`:
- Hand-rolled SigV4 (already pinned by the Engine against AWS's published vectors);
  **PUT of a single object only** — the same invariant that keeps the slice defensible.
- Path-style addressing `{endpoint}/{bucket}/{key}`; required signed headers `host`,
  `x-amz-date`, plus `x-amz-content-sha256` (full-payload hash — we already hold it from
  the export).
- Streaming body: an `httpx.AsyncByteStream` over the spool file with explicit
  `Content-Length`; full-payload signature, **no aws-chunked encoding** — the Engine's
  invariant ("chunked payload signing → take a real S3 client") is about signed chunking,
  not bounded transfer, so it is respected.
- Errors sanitized: never log/echo credentials or object contents.

### 4.3 Scheduler — `core/snapshot_scheduler.py`

`CacheSnapshotScheduler`:

- **Next-fire**: the earliest Friday 05:00:00 UTC strictly after `now` (UTC, no DST →
  exact). Recomputing from `now` each cycle (never a fixed-length sleep) makes a long GC
  pause or slow run self-correct.
- **Loop**: `start()` spawns one owned task (structured concurrency: created in
  `_lifespan`, cancelled and awaited in shutdown). Per fire: run the export with bounded
  exponential-backoff retries (3 attempts, jittered), record outcome, reschedule.
- **Single-flight**: one slot — a fire that finds the previous run still in flight
  **skips and logs** (weekly cadence: there is always a next Friday; there is no queue).
- **No catch-up**: starting Friday 05:01 runs next Friday (locked decision 2).
- The task is fully isolated: every exception is logged and contained; the request path
  cannot be touched by a scheduler/export failure.

### 4.4 Config — `aigateway/config.py` (`AIGW_` prefix, validation aliases)

- `cache_snapshot_enabled: bool = False` — opt-in, matching the cache's
  `ConfiguredCacheAvailability` stance; the chart turns it on where Garage is deployed.
- `cache_snapshot_cron: str = "0 5 * * 5"` — strict parser; v1 only accepts that form
  (UTC), parsed at startup.
- `cache_snapshot_s3_endpoint_url` (required when enabled), `…_bucket` (default
  `screamingface-cache-snapshots`), `…_region` (default `garage`, mirroring the Engine),
  `…_access_key` / `…_secret_key` (SecretStr, never logged).
- `cache_snapshot_timeout_s` (default 600), `cache_snapshot_max_bytes` (default 512 MiB).
- Fail-fast at startup when enabled but missing endpoint/keys — the same refusal shape as
  the Engine's `runner="k8s"` + filesystem check.

### 4.5 Lifespan wiring (`aigateway/main.py` `_lifespan`)

After the existing startup work: if `cache_snapshot_enabled`, build the exporter + store,
construct the scheduler, `app.state.cache_snapshot_scheduler = scheduler`,
`scheduler.start()`. Shutdown: `await scheduler.stop()` in `finally` (cancelled task is
awaited — no orphan).

### 4.6 Chart — `apps/aigateway/charts/aigateway/`

- `values.yaml` gains a `snapshot:` block: `enabled`, `garage.enabled` (bundled Garage,
  mirroring the Engine's `garage.yaml` StatefulSet + self-configuring flags, own bucket
  `screamingface-cache-snapshots`), `storage.endpointUrl/bucket/region/accessKey/secretKey`
  (external-endpoint override; defaults filled from the bundled Garage), `schedule`.
- New Secret template (`snapshot-secret.yaml`) holding `AIGW_CACHE_SNAPSHOT_S3_ACCESS_KEY`/
  `_SECRET_KEY`; the Garage pod adopts the same pair via `GARAGE_DEFAULT_ACCESS_KEY`/
  `_SECRET_KEY` (one source, two consumers — same invariant as the Engine).
- `configmap.yaml` emits the snapshot env keys; the Deployment `envFrom` picks them up
  (existing pattern). No CronJob — the schedule lives in the process.

## 5. Concurrency analysis

| Shape | Named problem | Handling |
|---|---|---|
| DB producer → gzip → file → S3 PUT | Producer–consumer | Bounded streaming: asyncpg chunk → `to_thread` gzip write → file; S3 body streams with known length. No unbounded queue at any stage; memory is O(chunk). |
| Fire while a previous run is in flight | Single-flight | One owned task slot; busy ⇒ skip + log (mirrors `CacheUploadRunner.busy()`). |
| Restart mid-window / re-run | Idempotency | Timestamped unique keys; re-running is harmless (no overwrite). |
| Task must not outlive scope | Structured concurrency | Task created/awaited inside `_lifespan`; cancelled in `finally`. |
| Compression + file I/O on the loop | Blocked event loop | `asyncio.to_thread` around gzip write; DB reads async via asyncpg. |
| Retried export must not double-write | Idempotency | Same key space; a retry writes the same (or a fresh) timestamped pair. |
| Cache mutated mid-export | MVCC snapshot | A single `COPY (SELECT …)` sees one consistent snapshot — no torn rows. |
| Timezone/clock drift | — | UTC only (no DST); next-fire recomputed from `now`; `zoneinfo("UTC")`. |

## 6. Test plan

P0 — round-trip integrity:
- Export → run through the **existing** `load_snapshot` (merge into a scratch Postgres) →
  `response_json` byte-identical, `row_count` == manifest, `sha256` == `digest_matches`.
- Byte layout: header line exactly `CopyBlockSource` accepts; `\.` terminator; epilogue
  ignored. SigV4 vs AWS published vectors (port the Engine's existing test).

P0 — schedule: `next_fire` boundaries — Friday 05:00:00 exactly (→ next week, no
catch-up), Friday 04:59 (→ 05:00 today), Saturday (→ next Friday), any Monday; UTC-only.

P0 — single-flight: second fire while busy ⇒ skip, no overlap; scheduler stop cancels
and awaits the task.

P1 — failure containment: Garage down ⇒ 3 backoff attempts then clean failure, and a
concurrent `/v1/chat/completions` cache hit during an export is unaffected; task never
leaks on shutdown.

P1 — MVCC consistency: export while rows are being inserted concurrently ⇒ the archive
matches a single point-in-time (no torn/partial rows).

P2 — e2e (local-k8s/compose): chart renders Garage + env; the scheduled run lands in
`cache-snapshots/…` in `screamingface-cache-snapshots`; `restore-cache` round-trips.

Gaps/assumptions: real-Garage e2e needs the local cluster; Postgres-only (sqlite refuses
with the loader's existing unsupported-database semantics); no metrics dashboard.

## 7. Observability

- One INFO line per run: `rows`, `sha256[:12]`, object keys, duration.
- WARN on retry; ERROR on terminal failure (with cause, sanitized).
- Last-run outcome on `app.state` (like `CacheUploadRunner.jobs()` records) for future
  admin surface; not exposed in v1.

## 8. Risks

- **Silent corruption** (a snapshot that loads but serves wrong bytes): closed by P0
  round-trip tests + manifest checksum/revision checks the existing loader already enforces.
- **Backup starvation** (pod temp disk fills): capped spool, loud failure.
- **Request-path interference**: dedicated DB connection + streamed I/O; P1 containment
  test proves it.
- **Week of data lost** if the gateway is down at 05:00: accepted by the no-catch-up
  decision; next Friday is the backstop.

## 9. Follow-ups (not v1)

- Manual/on-demand admin trigger (reuses the same runner + single-flight slot).
- In-app retention (LIST/DELETE signing) if keep-all ever exceeds the bucket.
- Multi-replica safety: Postgres advisory lock or k8s CronJob.

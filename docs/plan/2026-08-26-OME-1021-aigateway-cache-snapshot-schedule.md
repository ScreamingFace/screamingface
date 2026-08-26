# OME-1021 — Implementation plan

**Spec:** `docs/spec/2026-08-26-OME-1021-aigateway-cache-snapshot-schedule.md`
· **Ledger:** `docs/work/aigw/2026-08-26-OME-1021-cache-snapshot-schedule.md`
· **Branch:** `OME-1021-aigateway-cache-snapshot` · **Stack:** aigateway

Gates after every step:
`uv run .claude/scripts/run_gates.py aigateway --base origin/main`

## Ordering principle

The byte contract is the product — an archive that does not round-trip through the
existing loader is worse than no archive, because it fails *silently* at restore time. So
the emitter and its round-trip proofs land first, before any transport or scheduling
exists. Transport second (signing defects fail closed as 403s, so they are cheap to land
once the bytes are right), scheduling third (pure logic, fake-clock testable), wiring and
chart last.

---

### Step 1 — the byte emitter (`core/request_cache/snapshot_export.py`)

**RED:** given a fake connection whose `copy_from_query` streams known COPY-text chunks,
the exporter produces a gzip file that (a) `open_snapshot_stream` + `CopyBlockSource`
parse — header lists `CANONICAL_COLUMNS` verbatim, rows come back byte-identical through
the `\.` terminator; (b) hashes to exactly the manifest's `sha256` on disk; (c) declares
`row_count` parsed from the `'COPY <N>'` status string; (d) stamps `revisions` from the
injected revision source, and the sidecar passes `parse_manifest` + `digest_matches`.

**GREEN:** `CacheSnapshotExporter` with injected connection factory, revisions source,
clock, and spool dir; the hashing tee over the raw file; `asyncio.to_thread` for every
gzip write; spool cleanup in `finally`; typed `SnapshotExportError` hierarchy including
`SnapshotExportUnsupportedDatabase` and the `max_bytes` refusal.

**Why first:** everything downstream (store, schedule, chart) is glue; this is the only
step where a defect destroys data instead of failing loudly.

---

### Step 2 — real-Postgres round-trip (integration)

**RED (integration, mirroring `test_cache_snapshot_upload_postgres.py`'s harness):** seed
rows through the ORM → `export()` → feed the artifact to the **existing**
`load_snapshot(mode="merge")` into a scratch database → every `response_json` is
byte-identical, `row_count`/`sha256` agree with the manifest, and re-uploading the same
artifact through `POST /v1/admin/cache/snapshots` semantics is accepted (manifest
verified, no `revisions_unverified` warning).

**RED, additionally (MVCC):** insert rows *while* the export streams → the archive
contains exactly one point-in-time view (no torn rows, count matches a snapshot count).

**GREEN:** none — Step 1's exporter must pass as-is; any failure is an exporter defect.

---

### Step 3 — SigV4 + object store (`core/sigv4.py`, `core/object_store.py`)

**RED:** signing matches AWS's published test vectors (port the Engine's pinned test);
`S3ObjectStore.put` sends path-style `{endpoint}/{bucket}/{key}`, signed `host`,
`x-amz-date`, `x-amz-content-sha256` (full-payload hash taken from the exporter), a
streaming `httpx.AsyncByteStream` body with explicit `Content-Length`, and **no**
aws-chunked encoding; non-2xx raises a sanitized `S3StorageError` that carries no
credential material.

**GREEN:** the PUT-only slice, mirroring the Engine's `artifacts/sigv4.py` +
`artifacts/s3.py` structure and docstring invariants (kept honest by copy, not import —
the two apps must not depend on each other).

---

### Step 4 — the scheduler (`core/snapshot_scheduler.py`)

**RED:** `next_fire` returns the earliest Friday 05:00:00 UTC **strictly after** now —
Friday 04:59 → today 05:00; Friday 05:00:00.000 → next week (no catch-up, locked decision
2); Saturday/Monday → next Friday. The loop (fake clock + injectable sleep) fires the
exporter once per deadline, **skips and logs when the previous run is still in flight**
(single-flight), retries a failing run 3× with jittered exponential backoff, records each
outcome, and recomputes the next deadline from `now` each cycle.

**RED, lifecycle:** `stop()` cancels and awaits the owned task — no orphan survives; a
scheduler failure never escapes into the caller.

**GREEN:** `CacheSnapshotScheduler` — one owned task, injectable clock/sleep/exporter,
outcome log on `app.state`-shaped records.

---

### Step 5 — settings + fail-fast (`aigateway/config.py`)

**RED:** `AIGW_CACHE_SNAPSHOT_*` fields parse (enabled default false; cron default
`0 5 * * 5`; endpoint/bucket/region/keys; timeout; max_bytes); an unknown cron form is
refused at startup; enabled-but-missing endpoint/keys raises the same refusal shape as
the Engine's `runner="k8s"` + filesystem check (spec §4.4).

**GREEN:** the fields + validators; nothing else moves.

---

### Step 6 — `_lifespan` wiring + containment

**RED:** with the feature enabled, the app builds exporter + store + scheduler on
`app.state` and starts it at startup; shutdown awaits it. **Containment:** while an
export is in flight (slow fake store), a `/v1/chat/completions` cache **hit** completes
unaffected and a store failure surfaces as a log line, not an app error.

**GREEN:** the `_lifespan` block (start after existing startup work; `await stop()` in
`finally`), guarded by `cache_snapshot_enabled`.

---

### Step 7 — chart (`apps/aigateway/charts/aigateway/`)

**GREEN (render checks, no live cluster):** `snapshot:` values block; new
`snapshot-secret.yaml` + bundled Garage StatefulSet/Service/ConfigMap mirroring the
Engine's `garage.yaml` (single-node, self-configuring, bucket
`screamingface-cache-snapshots`, key pair adopted from the same Secret the gateway
reads); `configmap.yaml` emits the snapshot env keys. `helm template` renders correctly
in both modes — bundled Garage (defaults filled) and `garage.enabled: false` with an
external `endpointUrl` (which must then be set or the chart leaves the app to fail fast
per Step 5).

**Why render-only:** real-Garage e2e is the P2 local-k8s pass (spec §6), not a CI gate.

---

### Step 8 — close out

Ledger Outcome filled · conventional commits with `Refs: OME-1021` · PR · green CI ·
squash-merge · close comment per the card's `close_template` · close OME-1021 in Linear
**and** the `docs/tasks/` mirror.

## Verification

1. Gates green: `uv run .claude/scripts/run_gates.py aigateway --base origin/main`.
2. Scratch Postgres: seed → export → `load_snapshot` merge → byte-identical payloads;
   admin-upload path accepts the same artifact with manifest verification.
3. `helm template` for both storage modes renders; no CronJob exists (schedule is
   in-process).
4. `git grep -n "boto3\|aioboto3" apps/aigateway` returns nothing (the slice stays
   hand-rolled, per spec §4.2).

## Risks

| Risk | Handling |
|---|---|
| Silent archive corruption | Steps 1–2 land before anything can ship a bad archive; loader-side `sha256`/`row_count`/`revisions` gates remain the safety net |
| Event-loop stalls during export | Every gzip write off-loop (`to_thread`); Step 6 proves a cache hit completes mid-export |
| Pod temp disk fill | `max_bytes` cap, loud refusal, spool cleanup in `finally` |
| Overlapping runs (slow export vs next fire) | Single-flight slot: skip + log (weekly cadence has no queue) |
| Week skipped when gateway is down at 05:00 | Accepted (locked decision 2); next Friday is the backstop |

## Out of scope

Manual/on-demand admin trigger · in-app retention/pruning (keep-all) · metrics
dashboard · multi-replica scheduling · restore automation (already exists) · any Engine
chart change (the aigateway Garage is its own instance, by design).

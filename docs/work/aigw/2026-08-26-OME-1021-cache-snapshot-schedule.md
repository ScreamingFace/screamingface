---
ticket: OME-1021
stack: aigateway
status: planned   # planned | in_progress | done | blocked
started: 2026-08-26
finished:
---

# OME-1021 — Snapshot the aigateway response cache to Garage every Friday 05:00 UTC

## Intent

Archive the global response cache weekly so a deployment loss does not lose paid-for
answers: every Friday 05:00 UTC, stream `request_cache_entries` into the existing
OME-952 snapshot format and PUT it (archive + manifest) to a Garage bundled in the
aigateway chart, in a dedicated bucket/prefix that cannot mix with the Engine's
artifacts. Strictly next-Friday (no catch-up), keep-all, schedule-only. Spec (approved
2026-08-26): `docs/spec/2026-08-26-OME-1021-aigateway-cache-snapshot-schedule.md`.

## Planned changes

- `apps/aigateway/src/aigateway/core/request_cache/snapshot_export.py` (new) — streaming
  exporter, dedicated asyncpg connection, gzip+sha256 tee, manifest emission
- `apps/aigateway/src/aigateway/core/sigv4.py` + `core/object_store.py` (new) — PUT-only
  S3 client, port of the Engine's proven slice
- `apps/aigateway/src/aigateway/core/snapshot_scheduler.py` (new) — weekly loop,
  single-flight, backoff, owned task
- `apps/aigateway/src/aigateway/config.py` — `AIGW_CACHE_SNAPSHOT_*` settings, fail-fast
- `apps/aigateway/src/aigateway/main.py` — `_lifespan` start/stop wiring
- `apps/aigateway/charts/aigateway/` — `snapshot:` values block, Garage StatefulSet +
  Secret, configmap keys, deployment env
- tests under `apps/aigateway/tests/unit/` + `tests/integration/` (P0 round-trip, schedule
  math, single-flight; P1 containment, MVCC)

## Test plan

- P0: exported bytes round-trip through the existing `load_snapshot` (byte-identical
  `response_json`, manifest `row_count`/`sha256`/`revisions` agree); `next_fire` boundary
  math (strictly next Friday 05:00 UTC); single-flight skip + shutdown join
- P1: Garage-down backoff then clean failure while a cache-hit chat completes; MVCC
  consistency under concurrent inserts; SigV4 vs AWS vectors
- P2: local-k8s e2e — scheduled run lands in `cache-snapshots/…`; `restore-cache`
  round-trips

## Acceptance

- With `AIGW_CACHE_SNAPSHOT_ENABLED=1` (chart default where Garage is on), a run fires at
  Friday 05:00 UTC and both objects exist under the dedicated prefix; nothing appears in
  the Engine's artifacts bucket
- The existing admin upload path loads the exported archive (merge) without warnings
- Gates green: `uv run .claude/scripts/run_gates.py aigateway --base origin/main`

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">

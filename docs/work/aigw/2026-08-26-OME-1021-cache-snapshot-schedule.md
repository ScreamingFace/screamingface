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

- **Actual files:** spec/plan/mirrors (docs/) + `core/request_cache/snapshot_export.py`,
  `core/sigv4.py`, `core/object_store.py`, `core/snapshot_scheduler.py`, `config.py`
  fields+validator, `main.py` lifespan wiring, chart (`values.yaml`, `_helpers.tpl`,
  `snapshot-secret.yaml`, `garage.yaml`, `configmap.yaml`, `deployment.yaml`); tests:
  `test_snapshot_export.py`, `test_cache_snapshot_export_postgres.py`,
  `test_sigv4.py`, `test_object_store.py`, `test_snapshot_scheduler.py`,
  `test_cache_snapshot_settings.py`, `test_cache_snapshot_wiring.py`
- **Commits:**
  - `3509987a` docs: spec, plan, and OME-1021 mirrors
  - `2b73c7ab` feat: cache snapshot exporter — OME-952 byte emitter
  - `80ff458c` test: export round-trip vs real Postgres
  - `fd63bbcb` feat: PUT-only SigV4 object store
  - `5a645f21` feat: weekly cache-snapshot scheduler
  - `157a2531` feat: AIGW_CACHE_SNAPSHOT_* settings, fail-fast
  - `fff359bc` feat: arm the scheduler in the lifespan
  - `74d3d2af` feat: chart wiring (Garage, secret, env)
- **Gates:** `run_gates.py aigateway --base origin/main` — ALL GATES GREEN (ruff,
  format, pyright, check_no_enterprise, pytest 92%+ cov); helm lint + `helm template`
  in all three modes + values-prod render + `verify_chart_wiring.py` 31/31
- **Deviations:** `pg_dump` is absent in this dev environment, so the pre-existing
  `test_cache_snapshot_upload_postgres.py` cannot run locally (CI has it); the new
  export Postgres tests (no pg_dump dependency) pass. No plan deviations.

## Review round 1 — P1 fixes (HupBaHa review, 2026-08-27)

- **C1 (P1) false-success redirects:** `object_store.put()` accepted any status below 400,
  so a 301/307/308 (httpx does not follow redirects) returned as success — the spool was
  deleted and `published` logged for an object never stored. Now every non-2xx fails;
  redirects get a dedicated error naming the `Location` target and the endpoint variable
  (the signature is bound to the signed host and path, so redirects are never followed).
  Tests: 301/307/308 assert failure, actionable message, no credential leak, exactly one
  request.
- **C3 (P1) export/restore cap mismatch:** `cache_snapshot_max_bytes` defaulted to 512 MiB
  against the OME-952 upload cap of 256 MiB — a 300 MiB archive published fine and was
  unrestorable. Default lowered to 256 MiB (both caps count the COMPRESSED archive — the
  review's "uncompressed COPY bytes" note was corrected during verification), plus a
  Settings validator refusing `snapshot_max > upload_max` when snapshots are enabled.
  `DEFAULT_MAX_SNAPSHOT_BYTES` aligned; spec §4.1/§4.4 updated to stay truthful.
- **C0 (P1) NetworkPolicy captured bundled Garage:** selectorLabels (name+instance) matched
  Garage Pods too, so the default 9105-only policy denied the gateway's PUTs to
  Garage:3900. Gateway Deployment now carries `component: gateway` (matching the migrate
  Job's existing pattern); NetworkPolicy and Service selectors tightened to it; new
  Garage-scoped policy (renders with `snapshot.enabled && garage.enabled &&
  networkPolicy.enabled`) admits only this release's gateway Pods on 3900.
  `verify_chart_wiring.py`: +11 checks (42/42) incl. the policy/label pair and the
  no-policy render.
- **Gates:** focused 41 passed; full non-live suite 4094 passed; ruff, pyright (0 errors),
  check_no_enterprise, helm lint, `verify_chart_wiring.py` 42/42 all green.
- **Not addressed here (P2s, next commits):** external-store credential minting (C4),
  SQLite fail-late (C5), endpoint canonicalization (C6), main.py size (C7), and the
  downgraded-to-P2 replica guard (C2).

## Review round 1 — P2 fixes (2026-08-27)

- **C2 (P2) single-replica invariant enforced:** `aigateway.validateSnapshot` (_helpers.tpl,
  included from configmap.yaml) refuses the render when `snapshot.enabled=true` and
  gateway `replicaCount > 1`, naming the stamp-collision it prevents and the named
  future work (advisory lock / CronJob). Spec limitation line updated to say "enforced".
- **C4 (P2) no minted credentials for external stores:** snapshot-secret.yaml refuses
  external mode (`garage.enabled=false`, no existingSecret) unless BOTH keys are supplied;
  generation stays bundled-Garage-only (it adopts the pair at first boot). values.yaml
  storage comment updated.
- **C5 (P2) Postgres required when armed:** `Settings._validate_cache_snapshot` refuses a
  non-postgres:// DSN (notably the sqlite default) when snapshots are enabled — the
  arm-then-fail-every-Friday trap. DSN never echoed (credentials). Wiring tests adapted:
  postgres-form DSN in Settings (never dialed — `_run` replaced), ORM on sqlite via the
  documented `init_db` seam.
- **C6 (P2) origin-shaped endpoints only:** `S3ObjectStoreConfig.__post_init__` rejects
  base-path/query/fragment/userinfo/schemeless endpoints at construction — the signature
  covers `/<bucket>/<key>`, so anything else transmits a request it never signed
  (guaranteed SignatureDoesNotMatch). Trailing-slash origin accepted; PUT path unchanged.
- **C7 (P2) main.py back under 450:** builder + publish protocol moved verbatim to
  `core/snapshot_publish.py::build_snapshot_scheduler` (main.py 495 → 441); lifespan keeps
  start/stop only. Spec §4.5 updated.
- **Gates:** focused 44 passed; full non-live suite 4103 passed; ruff + format, pyright
  (0 errors), check_no_enterprise, helm lint, prod-values render, `verify_chart_wiring.py`
  47/47 (5 new refusal/external-generation checks) all green.

## Review round 2 — upgrade regression (2026-08-28)

- **C8 (P1) Deployment selector must not change:** round 0's C0 fix added
  `app.kubernetes.io/component: gateway` to the gateway Deployment's `spec.selector`.
  A Deployment selector is immutable after creation, so `helm upgrade` of any already
  installed release would fail with `field is immutable` — a failure fresh installs and
  render-only CI cannot see. The selector is back to name+instance (byte-identical to
  `origin/main`); the component label stays on the Pod template, which is mutable and is
  what the Service and both NetworkPolicies actually select on, so the C0 scoping holds
  unchanged.
- **Regression pin:** `verify_chart_wiring.py` now asserts the Deployment selector carries
  NO component key, next to the existing check that the Pod template does (48/48).
- **Gates:** helm lint (snapshot on) clean, prod-values render clean,
  `verify_chart_wiring.py` 48/48; rendered selector confirmed equal to `origin/main`'s.
- **Left open by the reviewer as non-blocking follow-ups:** redirect-target sanitization
  and Garage replica hardening.

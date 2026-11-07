---
ticket: OME-1810
stack: screamingface-engine
status: in_progress
started: 2026-11-02
finished:
---

# e5-p1-e7-sweeps-runs-routes — PR 4: the Run sweeps, the `/runs` routes and start binding

## Intent

PR 4 of the E5 P1 Engine stack (`docs/plan/2026-10-30-e5-p1-first-class-run.md`, units E7 and
E8; spec `docs/spec/2026-10-27-e5-p1-first-class-run.md`), stacked on PR 3 (#1639), under
`OME-1785`. It runs reconcile (R6) and retention (R7) at start and hourly, serves `/runs`
(§4.1, D6, D12), and binds a start to its Run's Candidate (R2). With it the Engine half of P1 is
complete: a Client can register a Run, read and cancel it, and see each Candidate settle.

## Planned changes

Paths under `apps/screamingface-engine/`:

E7, sweeps:
- `src/screamingface_engine/runs/sweeps.py` (new): one sweep is `reconcile()` then
  `expire(now - run_retention_s)`; run once at start and every `run_sweep_interval_s`; a failed
  sweep is logged and the cadence kept.
- `src/screamingface_engine/runs/wiring.py`: start the sweeper with the registry, stop it at
  shutdown. `install_runs` is the one call both `app.py` and `local.py` already make, so both
  modes get it from there.
- `src/screamingface_engine/config.py`: `run_sweep_interval_s` (default 3600).

E8, routes and binding:
- `src/screamingface_engine/runs/registry.py`, `store.py`: `register` returns the record and
  whether it was created (201 vs 200), `create` keeps its contract; `mark_scheduled` returns
  whether the start still stands (False once a cancel won).
- `src/screamingface_engine/rest/runs.py` (new): `POST/GET /runs`, `GET/DELETE /runs/{id}`, the
  owner (D6), Runs off as a plain 404, `run_not_found`, and the start-binding helpers.
- `src/screamingface_engine/rest/routes.py`: call sites only. Bind before scheduling, confirm
  after; the stop path extracted so `DELETE /runs/{id}` reuses it.
- `src/screamingface_engine/app.py`: mount the router.
- `CHANGELOG.md`, `README.md`: the `/runs` routes and the start headers.

## Test plan

- Sweeps: a sweep runs at start; reconcile writes only `lost` and no cost; with a surviving stream
  a Candidate live `run_lost_after_s` after its bind reads `lost`, a younger one is untouched; a
  hosted restart leaves a queued Candidate `scheduled` and its worker outcome settles it with its
  cost; after a local restart every in-flight Candidate reads `lost`; expire deletes only Runs
  older than `run_retention_s`; a failing sweep does not stop the loop.
- Routes: hosted without identity 401; local owner `local`; Runs off 404 without `run_not_found`;
  unknown or foreign id 404 `run_not_found` on every route; repeated `POST /runs` 200 and the same
  Run; `GET /runs` and `GET /runs/{id}` agree on state; `DELETE` 202 and stops live topics, 204
  when every Candidate is terminal; bad input 422.
- Start: a start under a canceled run 409 before anything is scheduled; the same start re-sent
  after a 503 schedules; a bind that fails on the database still schedules; a non-ASCII
  Candidate binds by index; a refused start leaves the Candidate `pending`; a cancel landing
  between bind and schedule stops the topic and answers 409; a start without the headers is
  unchanged (no existing start test edited).

## Acceptance

- Every test above green on SQLite (Postgres in CI); targeted runs locally, CI runs the gates.
- No prior test edited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `rest/stopping.py` (the stop path both `DELETE /` and
  `DELETE /runs/{id}` use). Tests: `test_run_sweeps.py`, `test_run_registry_start.py`,
  `test_runs_routes.py` (new), one test appended to `test_run_wiring.py`.
- **Commits:** one commit on `e5-p1-e7-sweeps-runs-routes`.
- **Gates:** targeted locally: ruff and pyright clean on `rest/`, `runs/`, `app.py` and the new
  tests; the layering check OK; the engine unit suite passed (6774). CI runs the full gates.
- **Deviations:**
  - The sweeps start from `install_runs`, the one call `app.py` and `local.py` both make, not from
    each file.
  - The port gains `register`, which also says whether it created the Run (201 vs 200); `create`
    keeps its contract.
  - `run_not_found`, `run_canceled` and `candidate_already_started` are the Problem's `code`, as
    every other Engine code is; the type stays `about:blank`.
  - Not in the spec: an `X-SF-Run-Candidate` that is not an index of the Run answers 400
    `malformed_header`; a hosted `/runs` call without identity answers 401 `identity_required`;
    the sweep interval is a setting, `run_sweep_interval_s` (1 h).

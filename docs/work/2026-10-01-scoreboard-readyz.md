---
ticket: OME-944
stack: scoreboard
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# scoreboard-readyz — split readiness from liveness with a DB-aware /readyz

## Intent

Both k8s probes hit the static `/healthz`, so a pod whose database is gone stays Ready and every
submission 503s. Add `/readyz` (a bounded `SELECT 1` on the Tortoise default connection, fail
closed → 503), keep `/healthz` pure liveness (never touches the DB — a dependency-coupled liveness
probe turns one bad backend into a restart loop), and point the chart's readinessProbe at
`/readyz`.

## Planned changes

- `apps/scoreboard/src/scoreboard/routes/health.py` — add `GET /readyz`.
- `apps/scoreboard/charts/scoreboard/values.yaml` — `readinessProbe.httpGet.path: /readyz`.
- `apps/scoreboard/charts/scoreboard/templates/tests/test-connection.yaml` — curl `/readyz`.
- `.github/scripts/verify_chart_wiring.py` — scoreboard section: liveness `/healthz`, readiness
  `/readyz`, distinct (default + prod values). `.github/workflows/charts.yml` — trigger on
  `apps/scoreboard/charts/**` so the assertion actually runs on scoreboard chart PRs.
- Docs: `apps/scoreboard/README.md`, `apps/scoreboard/DEPLOYMENT.md` probe statements.
- `apps/scoreboard/tests/unit/test_readyz.py` (new).

## Test plan

- readyz is 200 `{"status":"ready"}` with a reachable DB;
- readyz fails (503) when the DB is down — real unreachable Postgres URL, no mocks — and healthz
  stays 200 in the same app;
- readyz fails closed (503, not 500) when the check raises a non-DB error or exceeds its deadline.

## Acceptance

- `run_gates.py scoreboard` green; `verify_chart_wiring.py` green incl. new scoreboard checks;
  `helm lint` + `helm template` (default + prod) of the scoreboard chart succeed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `docs/tasks/2026-08-22-OME-944-scoreboard-readyz.md`
  (mirror → `in_review`).
- **Commits:** single commit `feat(scoreboard): split readiness from liveness with a DB-aware /readyz` (see PR).
- **Gates:** `run_gates.py scoreboard` — ALL GATES GREEN; `verify_chart_wiring.py` 115/115 (2 new
  scoreboard checks); `helm lint` scoreboard chart clean; `check_mirror_status.py` exit 0.
- **Deviations:** the scoreboard chart was not covered by `verify_chart_wiring.py` or
  `charts.yml` at all, so "passes verify_chart_wiring.py" would have been vacuous — added a
  scoreboard probe section (default + prod values) and the chart path to `charts.yml` triggers.
  `/readyz` checks connectivity only (`SELECT 1`), not schema — the breaking-migration window in
  DEPLOYMENT.md is unchanged (doc corrected to say so).

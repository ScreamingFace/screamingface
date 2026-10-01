---
ticket: OME-1452
stack: scoreboard
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# scoreboard-db-pool-readiness — size the DB pool explicitly; readiness on a reserved connection

## Intent

`/readyz` (OME-944) runs `SELECT 1` on the `default` connection, capped at 2 s. That connection's
pool has no explicit size, so under load the probe queues behind request traffic for a pooled
connection; a wait over 2 s marks the pod unready, and with 3 prod replicas a load spike can pull
every pod out of the Service at once. This unit makes the pool size explicit (Settings + chart)
and takes the readiness probe off the request pool entirely.

## Effective default pool size (verified, not assumed)

Installed: `tortoise-orm 1.1.8`, `asyncpg 0.31.0` (apps/scoreboard/uv.lock).

- `tortoise/backends/base_postgres/client.py:87-88` —
  `self.pool_minsize = int(self.extra.pop("minsize", 1))`,
  `self.pool_maxsize = int(self.extra.pop("maxsize", 5))`.
- `tortoise/backends/asyncpg/client.py:53-54` passes them as `min_size`/`max_size` to
  `asyncpg.create_pool`, overriding asyncpg's own defaults (`asyncpg/pool.py:1075-1077`:
  `min_size=10, max_size=10`), which therefore never apply.
- The prod `SCOREBOARD_DATABASE_URL` carries no `minsize`/`maxsize`/`min_size`/`max_size` query
  parameter today, so the **effective pool is min 1 / max 5 per pod** — the ticket's belief holds.

## Design decision

Options: (A) a reserved connection for readiness, (B) explicit `maxsize` + probe
`failureThreshold`, (C) both.

**Chosen: A, plus the explicit sizing the ticket requires anyway. No `failureThreshold` change.**

- A removes the failure mode instead of tolerating it: the probe gets its own Tortoise connection
  alias (`readiness`, a pool of exactly one) on the same database, so request traffic can never
  occupy the connection the probe needs. Readiness then answers the question it is for — "can this
  pod reach its database" — and not "is this pod's pool momentarily busy".
- A is provable by a deterministic test: hold every connection in the `default` pool, call
  `/readyz`, assert 200. B is not: a `failureThreshold` is kubelet behaviour, so the only test
  is a chart render, which proves the number is there, not that readiness stops flapping.
- B alone only delays the flap (3 × 10 s already, since the k8s default `failureThreshold` is 3
  and the chart leaves it unset); sustained saturation still unreadies every replica. Adding it
  on top of A buys nothing A does not already give, so YAGNI.
- Sizing: `SCOREBOARD_DB_POOL_MINSIZE=1`, `SCOREBOARD_DB_POOL_MAXSIZE=5` — explicit, equal to
  today's effective values, so this unit changes no capacity. Raising the max is a load-data
  decision, not a guess to make here. Connection budget: 3 replicas × (5 + 1 reserved) = 18
  (was 15).
- Applied only to PostgreSQL URLs: the SQLite client turns every extra URL parameter into a
  `PRAGMA`, so a `maxsize` there would be an unknown pragma.
- Only the web app gets the readiness connection and the sizing (`init_db(..., pool=...)`); the
  CLIs and the migration CLI's `TORTOISE_CONFIG` are unchanged.

## Planned changes

- `apps/scoreboard/src/scoreboard/config.py` — `db_pool_minsize`, `db_pool_maxsize` (+ validation).
- `apps/scoreboard/src/scoreboard/db.py` — `PoolSize`, `READINESS_CONNECTION`,
  `build_server_tortoise_config`, `init_db(..., pool=None)`.
- `apps/scoreboard/src/scoreboard/main.py` — lifespan passes the pool size.
- `apps/scoreboard/src/scoreboard/routes/health.py` — probe uses `READINESS_CONNECTION`.
- `apps/scoreboard/charts/scoreboard/values.yaml`, `templates/configmap.yaml` — the two vars.
- `.github/scripts/verify_chart_wiring.py` — the configmap renders both, ints, min ≤ max.
- `apps/scoreboard/DEPLOYMENT.md` — pool sizing + helm-test-fails-while-DB-down note.
- New tests: `tests/unit/test_db_pool.py`, `tests/unit/test_readyz_pool_postgres.py`;
  `.github/workflows/scoreboard-tests.yml` names the new PostgreSQL module.

## Test plan

- Settings: defaults 1/5; env override; reject maxsize < 1, minsize < 0, minsize > maxsize.
- Config builder: postgres URL gains minsize/maxsize and keeps existing query params (`schema`);
  readiness connection is the same database with a pool of exactly one; SQLite URLs are untouched;
  `TORTOISE_CONFIG` (migration CLI) has no readiness connection.
- Saturation (SQLite, deterministic): with the `default` connection held, `/readyz` is 200.
- Saturation (PostgreSQL, CI lane): with all `maxsize` default-pool connections held, `/readyz`
  is 200; control — the same saturation makes a `default`-connection probe time out.
- Existing readyz tests stay green unmodified (DB down → 503, timeout → 503, non-DB error → 503).

## Acceptance

- Pool size explicit in Settings and the chart; probe uses a reserved connection; deterministic
  saturation tests green; `run_gates.py scoreboard` and `verify_chart_wiring.py` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `docs/tasks/2026-10-01-OME-1452-scoreboard-db-pool-readiness.md`
  (mirror). `PoolSize` lives in `config.py` (re-exported from `db.py`) because `db` imports
  `config`, not the reverse.
- **Commits:** one — `fix(scoreboard): reserve a readiness DB connection and size the pool explicitly`.
- **Gates:** `run_gates.py scoreboard` ALL GATES GREEN (append-only, ruff, ruff format, pyright,
  pytest 867 passed / 9 skipped, total coverage 90%, `db.py`/`health.py`/`config.py` 100%, node
  portal tests). `verify_chart_wiring.py` 117/117. PostgreSQL lane run locally against a throwaway
  PostgreSQL (pgserver binaries, TCP 127.0.0.1): `test_readyz_pool_postgres.py` 2 passed — pool of
  3 fully checked out (`get_idle_size() == 0`), `/readyz` 200 on the reserved connection, and the
  control reproduces the flap (503) on `default`.
- **Deviations:** Linear left in Backlog until PR-open (caller allowed only the In Review move +
  PR link), so the In Progress transition was skipped. No `failureThreshold` change (see Design
  decision). No existing test changed.

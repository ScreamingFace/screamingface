# scoreboard

This service powers the ScreamingFace Leaderboard, the public surface where fusion results are ranked and every entry keeps the `url4` needed to re-run it. Independent re-run verification is not live yet (OME-414), so published scores are self-reported. Results are cached, so building on prior work is cheap. It is fed by the Client and Studio through the Engine. Public site: https://leaderboard.screamingface.ai. Docs: https://docs.screamingface.ai.

It now provides the runnable service shell, health route, settings, Tortoise database wiring, score-domain models, the initial migration, and the persistence/query store. HTTP ingestion and leaderboard routes land in follow-up tickets.

## Quick Start

```bash
cd apps/scoreboard
uv sync

uv run tortoise migrate
uv run uvicorn scoreboard.main:app --port 9106 --reload

# Sanity check
curl -sf http://localhost:9106/healthz
```

By default, local runs use a SQLite database file named `scoreboard.sqlite3` in the current working directory. Delete that file to reset local data. If you previously exported `SCOREBOARD_DATABASE_URL`, unset it first with `unset SCOREBOARD_DATABASE_URL` to use the default.

`/healthz` is a liveness probe only. It does not query the database and does not prove database connectivity.

### Running Against Local Postgres

Set `SCOREBOARD_DATABASE_URL` when you want to run against Postgres instead of the default local SQLite file.

```bash
docker run --rm -d --name sf-scoreboard-postgres \
  -e POSTGRES_USER=scoreboard \
  -e POSTGRES_PASSWORD=scoreboard \
  -e POSTGRES_DB=scoreboard \
  -p 5434:5432 \
  postgres:16-alpine

export SCOREBOARD_DATABASE_URL='postgres://scoreboard:scoreboard@localhost:5434/scoreboard'
uv run tortoise migrate
uv run uvicorn scoreboard.main:app --port 9106 --reload
```

Tortoise's built-in migration CLI is configured through `[tool.tortoise]` in `pyproject.toml`. Apply migrations with `uv run tortoise migrate`; running it a second time should be a no-op.

### Migration Verification

```bash
cd apps/scoreboard
uv run tortoise migrate
uv run tortoise migrate
```

The first run applies pending migrations. The second run should report that no migrations are pending.

## Configuration

Settings are read from environment variables with the `SCOREBOARD_` prefix.

| Variable | Default | Description |
| --- | --- | --- |
| `SCOREBOARD_HOST` | `127.0.0.1` | Host used by the `scoreboard` console script. |
| `SCOREBOARD_PORT` | `9106` | Port used by the `scoreboard` console script. |
| `SCOREBOARD_LOG_LEVEL` | `info` | Uvicorn log level. |
| `SCOREBOARD_DATABASE_URL` | `sqlite://./scoreboard.sqlite3` | Tortoise database URL. |
| `SCOREBOARD_CORS_ORIGINS` | `["*"]` | JSON list of allowed CORS origins. |
| `SCOREBOARD_PORTAL_DIR` | app-local `portal/` | Static portal directory. |
| `SCOREBOARD_PORTAL_ARTIFACTS_DIR` | app-local `artifacts/` | Public JSONL artifact directory. |
| `SCOREBOARD_AUTH_MODE` | `disabled` | `disabled` trusts client-supplied `submitted_by`; `cloudflare_headers` requires and trusts the mesh-verified `X-User-Email` header instead (OME-404, following OME-326). |
| `SCOREBOARD_ALLOWED_NETWORKS` | unset | Comma-separated CIDRs permitted to present `X-User-Email`. Only read (and mandatory) in `cloudflare_headers` mode. |

`SCOREBOARD_CORS_ORIGINS` defaults to `["*"]` because the scaffold has no authenticated routes and never sets cookies. D-SCORE-007 will tighten this once the leaderboard write path lands.

## Portal And Public Artifacts

The scoreboard service serves the demo portal at `/`. The portal UI, GET routes, and public JSONL artifacts are always unauthenticated. `POST /v1/scores` is unauthenticated while `SCOREBOARD_AUTH_MODE` stays at its default (`disabled`).

Public artifact routes are exact-file allowlisted and served as inline `text/plain`:

- `/livetruth-latest.jsonl`
- `/livetruth-latest.eval.jsonl`
- `/livetruth-masking.dataset.jsonl`

Do not publish `livetruth-latest.answer-key.jsonl` or generated-artifact globs. `livetruth-latest.jsonl` intentionally contains answers/context for the current demo, and `livetruth-latest.eval.jsonl` intentionally exposes the direct-eval rows including `expected_answer`.

## Development

```bash
cd apps/scoreboard
uv run pytest tests/unit/ -v

# The portal's pure logic runs under Node's built-in test runner. No package.json
# or lockfile — Node is the whole harness. Requires a local Node (CI pins 24).
node --test tests/portal/leaderboard-logic.test.js tests/portal/pareto-chart.test.js
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

The runtime default uses SQLite for local runs, and unit tests use SQLite through Tortoise's isolated `tortoise_test_context`, so the persistence layer can be validated without a local Postgres server. Postgres-backed tests can opt into a database URL by setting `SCOREBOARD_TEST_DATABASE_URL`.

## Layout

```
src/scoreboard/
  main.py            FastAPI app + Tortoise lifespan
  config.py          Settings
  cli.py             `scoreboard` console-script entry point
  db.py              Tortoise configuration/init helpers
  routes/
    health.py        GET /healthz
  scores/
    schemas.py       Pydantic DTOs for submissions and read models
    store.py         Tortoise-backed persistence/query store
    models/          Benchmark, Score, and IdempotencyKey Tortoise models
    migrations/      Tortoise built-in migrations
tests/
  unit/
```

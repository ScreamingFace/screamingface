---
ticket: OME-1008
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1008 — Persist before deliver, with idempotent replay

## Intent

`apps/report-intake` accepts a report, bounds it, classifies it — and then forgets it. This unit
gives the service its state: spec §5's one table, committed **before** any sink is reachable, a
24 h idempotency window that answers a replay with `200` and the original record, a 90-day
retention purge, and the `503` that tells a client nothing was stored so it must keep the report
on disk. It also installs the first real readiness probe, so `/readyz` stops being a constant.

Plan section: `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md` §6, against the
frozen contracts in §2 (§2.1 module ownership, §2.3 the `reports` table, §2.4 the environment
surface, §2.5 the readiness seam, §2.6 the problem catalogue, §2.7 the classification seam) and
§11's 18 resolved conflicts.

## Planned changes

- `apps/report-intake/pyproject.toml` — add `tortoise-orm[asyncpg]`, `[tool.tortoise]`.
- `apps/report-intake/src/report_intake/db.py` — Tortoise config + `init_db`/`close_db`
  (scoreboard's `db.py` as the template).
- `apps/report-intake/src/report_intake/config.py` — EDIT: `database_url`, `idempotency_ttl_h`,
  `retention_days` (§2.4's three names this item owns), plus scoreboard's sqlite-spelling
  normalizer.
- `apps/report-intake/src/report_intake/reports/models/{__init__,base,report}.py` — §2.3's table.
- `apps/report-intake/src/report_intake/reports/migrations/{__init__,0001_initial}.py` — one
  greenfield migration carrying **every** column any later item needs.
- `apps/report-intake/src/report_intake/reports/store.py` — `ReportStore`: persist, replay,
  purge, reachability. Raises `StorageUnavailable`; never returns a partial write.
- `apps/report-intake/src/report_intake/reports/store_pipeline.py` — `StorePipeline`, the
  `ReportPipeline` implementation that replaces `BindOnlyPipeline`.
- `apps/report-intake/src/report_intake/reports/retention.py` — the 90-day purge loop, a pure
  `sweep()` split from the loop so tests never sleep.
- `apps/report-intake/src/report_intake/routes/reports.py` — EDIT: map `StorageUnavailable` to
  `storage_unavailable()` (plan §6).
- `apps/report-intake/src/report_intake/main.py` — EDIT as a diff: add `lifespan=_lifespan`,
  swap the pipeline seam to `StorePipeline`, swap the readiness seam to the store probe.
- `apps/report-intake/tests/**` — behaviour-named tests; `conftest.py` gains a per-test database.
- `.github/workflows/report-intake-tests.yml` — the image job now migrates the container and
  asserts `/readyz` 200; the pre-migration 503 assertion stays and gains its real meaning.
- `apps/report-intake/README.md` — how to migrate; `docs/complexity-baseline.md` if the
  high-water marks move.
- This ledger.

## Test plan

- persist-before-deliver is structural: the row is committed before `submit` returns, and a
  pipeline holding no sink still answers `202` with `delivery.state = "pending"`.
- a replayed `Idempotency-Key` inside 24 h answers `200` with the **original** `ref`.
- the same key after 24 h is a new report with a new `ref`, and the stale row survives.
- two concurrent submissions of one key produce one row (the `IntegrityError` race path).
- storage down → `503`, `application/problem+json`, and the table is empty (plan §6, §11/15).
- `/readyz` answers 200 with the schema present and 503 with the store unreachable.
- the purge deletes a row older than the retention window and keeps one inside it.
- `next_attempt_at` / `lease_expires_at` are NOT NULL at insert (§2.3, §11/7, §11/8).
- `request_fingerprint` is diagnostic: two different reports sharing one key still replay the
  first (§6 — the dedup key identifies the submission, not its content).
- the migration and the models do not drift, asserted by reading the migration source.

## Acceptance

- `POST /v1/reports` persists, replays, and degrades to `503` exactly as spec §2.2/§2.3/§5 say.
- `0001_initial` carries every column in plan §2.3 — no later item needs a second migration for
  a column it already knew about.
- The purge runs inside `_lifespan`, never `app.router.on_startup` (§11/12).
- Gates green: `uv run pytest -q`, `uv run ruff check`, `uv run ruff format --check`,
  `uv run pyright`.

## Outcome

- **Actual files:** as planned. New: `src/report_intake/db.py`,
  `reports/models/{__init__,base,report}.py`, `reports/migrations/{__init__,0001_initial}.py`,
  `reports/store.py`, `reports/store_pipeline.py`, `reports/retention.py`, and
  `tests/unit/test_{report_store,store_pipeline,persistence_route,retention,db_wiring}.py`.
  Edited: `pyproject.toml`, `config.py`, `main.py`, `routes/reports.py`, `tests/conftest.py`,
  `tests/unit/test_readiness.py`, `.github/workflows/report-intake-tests.yml`, `README.md`,
  `docs/complexity-baseline.md`. **`routes/ready.py` is untouched** — the probe went on the
  existing seam, which is the whole point of plan §2.5.
- **Commits:** orchestrator-owned.
- **Gates:** `uv run .claude/scripts/run_gates.py report-intake` → ALL GATES GREEN.
  220 passed (59 new), ruff check + ruff format --check clean, pyright 0 errors,
  coverage 99.35% against the 80% floor, `uv lock --check` current, append-only test check
  clean. Complexity high-water marks unmoved by the store, the migration and the lifespan:
  C901 7, PLR0915 18, PLR0912 6, PLR0911 3.
- **Persist-before-deliver is a property of the call graph, not a convention.** `ReportStore`
  cannot reach a sink — there is nothing to import — and `StorePipeline.submit` returns only
  after `record` has committed. `OME-1009` adds delivery *after* that call rather than around
  it, so the ordering cannot be inverted by an edit that looks local.
- **Two failure modes the pinned dependencies make silent, both closed here.**
  (1) tortoise-orm 1.1.8's `ConnectionWrapper.__aenter__` takes the connection lock and *then*
  opens the connection, so a failed open never runs `__aexit__` and the lock is held for the
  life of the process — reproduced with an unwritable sqlite path: the first query raises and
  every query after it blocks forever. Every store call therefore carries a deadline
  (`STORAGE_TIMEOUT_S` 5 s, `PROBE_TIMEOUT_S` 2 s); without it `/readyz` *hangs* where spec
  §2.3's `503` belongs, and a request that never answers is strictly worse than one that fails.
  The container caught the same shape for real — see the Dockerfile's `/data` comment.
  (2) On the pinned starlette, `lifespan=` sets `Router.lifespan_context` directly and
  `router.startup()` is never called, so the retention purge registered on
  `app.router.on_startup` would never have run in production while its unit tests passed
  (§11/12). It starts inside `_lifespan`, the task is *owned* rather than left to a weak
  reference, and a test asserts both.
- **`RuntimeError` is in the storage-failure tuple deliberately.** Querying with no active
  Tortoise context — a pod whose `_lifespan` never opened the database — raises a bare
  `RuntimeError` from `tortoise.context.require_context`, not an ORM error. A tidier
  `except BaseORMException` would turn that into a `500`; it is a `503` by any reading of §2.3.
  The readiness probe goes further and catches everything, because the only two answers a
  kubelet can use are ready and not ready.
- **Tests read the table with `sqlite3`, from outside the ORM.** "The table is empty" after a
  `503` is worth asserting only if it is checked from outside the machinery that was supposed
  to have written it; and the schema under every test is built by the committed
  `0001_initial` rather than `generate_schemas()`, so a model the migration does not match
  fails here instead of on the first deploy.
- **Deviations:**
  - **`created_at` is set by the store, not `auto_now_add`.** `auto_now_add` stamps from the
    ORM's own clock while every policy reading the column (the idempotency window, the
    retention cut-off) compares against the store's injected one. Two clocks that agree in
    production and disagree under test is the worst of the three arrangements — the window
    would silently measure something other than what its tests assert.
  - **An expired idempotency key is released, the row is not deleted.** The column is unique,
    so a stale binding would refuse the next insert; the old row is still owed its 90 days.
  - **The `IntegrityError` race replays instead of failing.** Two concurrent submissions of one
    key both pass the lookup; the loser returns the winner's row. The end state — one report
    per key per window — holds either way, and the alternative fails a reporter's request for a
    race they cannot see.
  - **The CI image job now asserts both halves of readiness.** It already asserted `503` before
    the migration; it now runs `tortoise migrate` *inside the shipped image* and asserts `200`.
    Nothing else in CI runs `0001_initial` through the CLI an operator actually invokes.
  - **`PURGE_INTERVAL` is a constant, not a setting.** Plan §2.4 fixes the chart's rendered
    set, and a knob nobody would turn is one more name that can drift out of `Settings`. The
    retention *window* is configurable — that is the number with a policy behind it.

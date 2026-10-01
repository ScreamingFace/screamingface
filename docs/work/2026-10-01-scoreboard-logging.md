---
ticket: OME-937
stack: scoreboard
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# scoreboard-logging — configure a handler and honor SCOREBOARD_LOG_LEVEL

## Intent

The scoreboard's `scoreboard.*` loggers have no handler: `uvicorn.run()` configures only the
`uvicorn*` loggers, so every app record falls through to `logging.lastResort` (WARNING,
message-only) and INFO is discarded. `SCOREBOARD_LOG_LEVEL` is plumbed chart → configmap →
`uvicorn.run(log_level=...)` but governs only uvicorn. Port the engine's `logs.configure()`
(stdlib only, marker-attr idempotent handler, `propagate=False`) and call it from every entry:
`create_app` (all ASGI hosts) and the `seed` / `import_baselines` job CLIs.

## Planned changes

- `apps/scoreboard/src/scoreboard/logs.py` (new) — `APP_LOGGER="scoreboard"`,
  `LEVEL_ENV="SCOREBOARD_LOG_LEVEL"`, `configure(stream=None)`. No run-context machinery (that is
  engine-specific, OME-1069).
- `apps/scoreboard/src/scoreboard/main.py` — `configure()` in `create_app`.
- `apps/scoreboard/src/scoreboard/seed.py`, `import_baselines.py` — `configure()` in `main`.
- `apps/scoreboard/tests/unit/conftest.py` (new) — suite-wide isolation of the app logger plus a
  caplog bridge (engine OME-942 pattern), so `propagate=False` does not blind existing `caplog`
  tests.
- `apps/scoreboard/tests/unit/test_logs_configuration.py` (new).

## Test plan

- a `scoreboard.*` INFO record reaches the configured stream at the configured level;
- idempotent (no doubled records); foreign handler does not suppress ours;
- `propagate is False`; env lowers level to DEBUG; uvicorn's `trace` value does not crash;
- `create_app`, `seed.main`, `import_baselines.main` each install the handler.

## Acceptance

- `run_gates.py scoreboard` green; no new dependency; uvicorn's loggers untouched.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `apps/scoreboard/README.md` (env-var row now says the level
  governs the app's loggers too).
- **Commits:** see PR for OME-937 (single commit `fix(scoreboard): configure app logging and honor SCOREBOARD_LOG_LEVEL`).
- **Gates:** `run_gates.py scoreboard` — ALL GATES GREEN (ruff, format, pyright, pytest+cov ≥80, node portal tests).
- **Deviations:** (1) not a verbatim copy — the engine's run-context filter (OME-1069) is
  engine-specific and was left out. (2) `trace` (valid for uvicorn, same env var) maps to level 5
  so the Job CLIs, which never import uvicorn, do not crash on it. (3) new
  `tests/unit/conftest.py` caplog bridge must skip forwarding when pytest ≥9 has already attached
  its capture handler to the non-propagating logger, else records double (found via
  `test_a_page_logs_its_unrecognised_models_once_in_aggregate`). No prior test modified.

---
ticket: OME-1049
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# uvicorn-ws-ticket-log — close the remaining uvicorn log surfaces that leak a capability ticket

## Intent

`access_log=False` (OME-990) closed `uvicorn.access`, but `uvicorn.error` still logs
`"WebSocket <path?query>" [accepted]` on every WS handshake, and the Engine's WS URL is
`/ws?ticket=<token>` — so a live capability ticket (a credential that authorises a run) is
written to `runtime.log` on every attach. Separately `run_scoreboard()` still omits
`access_log=False`, and its stdout is relayed into the same `runtime.log`.

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/server.py` — a logger-level filter on
  `uvicorn.error` that strips the query string from any path argument, installed for every
  embedded server; `access_log=False` in `run_scoreboard()`.
- `packages/screamingface/tests/test_runtime_uvicorn_log_surfaces.py` — new tests.

## Test plan

- A WS-accept line carrying `?ticket=<secret>`, emitted on `uvicorn.error` through a handler
  bound inside `capture_runtime_log`, never reaches the captured log; the path `/ws` does.
- The filter survives a later `dictConfig` (each uvicorn Config re-runs it).
- The filter is installed once, however many servers are built.
- Records with no path argument / non-path args pass through unchanged.
- `run_scoreboard()` builds its server with `access_log=False` (config assertion mirroring
  `test_every_embedded_server_is_configured_without_an_access_log`).

## Acceptance

- No `ticket=` value from a WS handshake reaches `runtime.log`.
- Scoreboard's uvicorn runs with `access_log=False`.
- `run_gates.py screamingface` green; prior tests unmodified.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_runtime/server.py` (`_QueryStringRedactor` on the
  `uvicorn.error` logger, installed by `_server()` after each `uvicorn.Config`;
  `access_log=False` in `run_scoreboard()`), `tests/test_runtime_uvicorn_log_surfaces.py`
  (8 tests), plus the `docs/tasks/` mirror.
- **Commits:** `fix(screamingface): keep the WS capability ticket out of runtime.log` (this
  ledger's commit).
- **Gates:** `run_gates.py screamingface` ALL GATES GREEN — append-only, ruff, format,
  pyright, pytest 2111 passed / 26 skipped at 96.20% coverage, notebooks, build,
  distribution.
- **Empirical check:** a real uvicorn server (Engine venv) with a real `websockets` client
  on `/ws?ticket=SECRET123`: baseline logs `"WebSocket /ws?ticket=SECRET123" [accepted]`;
  with the redactor installed it logs `"WebSocket /ws" [accepted]` and the secret is absent.
- **Deviations:** the line is rewritten (query stripped), not suppressed — the ticket allowed
  either; keeping client/path/outcome preserves attach debuggability. The scoreboard gets
  only `access_log=False` (no redactor) — it serves no WebSocket, and the ticket scoped it
  to that one-word fix. No `docs/spec`/`docs/plan` artifacts: the Linear description is the
  spec (lane instruction).

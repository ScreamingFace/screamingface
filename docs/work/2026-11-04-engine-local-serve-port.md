---
ticket: unfiled   # backfilled at PR-open
stack: screamingface-engine
status: in_progress
started: 2026-11-04
finished:
---

# engine-local-serve-port — `screamingface-engine serve --local --port N`

## Intent

`serve --local` binds 9108, hardcoded. `screamingface up` lets a user pick the Engine port
(`--engine-port`), and the next unit starts the local Engine as a child process of `up` from an
Engine environment of its own — so the child must be told which port to bind. PR 1 of 3 of the
"local Engine serves every board" stack (OME-1620 / OME-1626).

## Planned changes

- `src/screamingface_engine/cli.py`: `serve --port N` (only with `--local`; the deployed `serve`
  keeps its hardcoded port, which IS the chart's containerPort). `_serve_local(port)`.
- `tests/unit/test_cli.py`: new tests, nothing prior touched.

## Test plan

- `serve --local` still serves local on 9108 (default unchanged).
- `serve --local --port 9111` hands 9111 to the local server.
- `serve --port 9111` without `--local` is a usage error (exit 2), never a deployed server on a
  moved port.
- `--port 0` / non-integer rejected by argparse.

## Acceptance

- The three tests above pass; ruff + pyright clean on the touched files; the prior CLI tests
  are untouched and green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `apps/screamingface-engine/src/screamingface_engine/cli.py` (`--port`,
  `_tcp_port`, `_dispatch_serve`), `apps/screamingface-engine/tests/unit/test_cli_local_mode.py`
  (5 new tests), `apps/screamingface-engine/README.md` (one usage line). As planned.
- **Commits:** see PR.
- **Gates:** `uv run --isolated pytest tests/unit/test_cli_local_mode.py tests/unit/test_cli.py`
  → 25 passed; ruff check + format clean; pyright 0 errors on the two touched files. Relevant
  tests only (owner rule); CI runs the full lane.
- **Deviations:** none.

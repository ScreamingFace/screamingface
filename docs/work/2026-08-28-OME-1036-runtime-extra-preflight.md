---
ticket: OME-1036
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-08-28
finished: 2026-08-28
---

# OME-1036 — Detect a missing [runtime] extra before the local stack boots

## Intent

`screamingface up` must refuse to start, with a message that names the missing modules and
the install command, when the `[runtime]` extra is absent — even on hosts (Colab) that
preinstall `uvicorn` and `fastapi`. Today the guard passes there, the `_serve` child dies
at `from tortoise import Tortoise`, and the log shows a raw `No module named 'tortoise'`
with no remediation. `doctor` shares the guard and reports the broken state as healthy.

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/server.py` — probe the extra-only
  modules with `importlib.util.find_spec`; raise the friendly error naming what is missing.
- `packages/screamingface/src/screamingface/_runtime/cli.py` — `ImportError` in `_serve`
  logs the install hint; `_wait_ready` includes the last runtime log lines when the child
  dies during startup.
- `packages/screamingface/README.md` — both install lines (hosted vs local stack) and a
  troubleshooting entry.
- `packages/screamingface/tests/test_runtime_cli.py` — new tests for the preflight, the
  hint, and the log tail.

## Test plan

- `_missing_runtime_modules` reports each absent module (fake finder), and only those.
- `require_runtime_extra` raises with the module names and `screamingface[runtime]` in the
  message (missing list injected; CI installs no extra).
- The probe list pins the extra differentiators (`tortoise`, `litellm`, …) — the Colab gap.
- `_serve` prints the install hint for an `ImportError`.
- `_wait_ready` includes the last log lines when the child has exited.

## Acceptance

- On a host with `uvicorn` preinstalled and `tortoise` absent, `up` fails in the parent
  process with an actionable message; `doctor` reports the missing modules.
- All stack gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `src/screamingface/_runtime/server.py`,
  `src/screamingface/_runtime/cli.py`, `README.md`, `tests/test_runtime_cli.py` (all under
  `packages/screamingface/`), plus the four SDLC docs. As planned.
- **Commits:** see `git log origin/main..HEAD` on `OME-1036-runtime-extra-preflight`.
- **Gates:** ruff check ✓ · ruff format ✓ · pyright 0 errors · pytest 1272 passed /
  17 skipped, coverage 95.02% (floor 95) · check_notebooks ✓ · uv build ✓ ·
  check_distribution ✓
- **Deviations:** none. The preflight probe runs before `enable_local_providers` so a
  refused boot leaves no environment mutation; spec already allowed this ordering.

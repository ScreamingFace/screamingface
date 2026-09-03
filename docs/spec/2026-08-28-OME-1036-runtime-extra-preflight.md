---
title: Detect a missing [runtime] extra before the local stack boots
ticket: OME-1036
status: approved
date: 2026-08-28
---

# Detect a missing [runtime] extra before the local stack boots

## Outcome

On a host without the `screamingface[runtime]` extra, `screamingface up` and
`screamingface doctor` say what is missing and how to fix it. No raw
`No module named 'tortoise'` line appears in a runtime log without the install command
beside it. This holds on hosts that preinstall `uvicorn` and `fastapi` (Colab ships them
through gradio), which is where the current guard passes by accident.

## Why the current guard fails

`require_runtime_extra()` imports `aigateway`, `scoreboard`, `screamingface_engine`,
`url4`, and `uvicorn`. The build hook vendors the four app sources into the wheel, and
their `__init__` files import nothing heavy, so four of the five imports succeed on a
plain install. Only `uvicorn` probes the extra, and Colab preinstalls it. The first
extra-only import the boot path reaches is `from tortoise import Tortoise` inside the
`_serve` child (`_migrate`), which dies with a raw `ModuleNotFoundError`.

## Preflight contract

- `require_runtime_extra()` probes a fixed tuple of module names with
  `importlib.util.find_spec`. It does NOT import them: the check must stay fast (no
  `litellm` import at guard time) and must run in CI, which installs no runtime extra.
- The tuple lists the modules that only the extra provides and that the local boot path
  needs: `aiosqlite`, `bcrypt`, `cryptography`, `fastapi`, `kubernetes`, `litellm`,
  `prometheus_client`, `pydantic_settings`, `tortoise`, `uvicorn`. The tuple lives beside
  the `runtime` extra in `pyproject.toml` and both change together.
- On any missing module, the error names every missing module and ends with
  `Install "screamingface[runtime]"`.
- The vendored-app imports and checkout verification (OME-1001) stay as they are, after
  the probe.

## Error translation contract

`_serve` handles `ImportError` before the generic `Exception` branch and appends the
install command to the `SCREAMINGFACE_RUNTIME_ERROR` line. Any future gap in the preflight
list still produces an actionable log line.

## Startup failure contract

When `_wait_ready` observes a dead `_serve` child, the raised error includes the last
runtime log lines (up to 15), not only the log path. The user sees the cause on screen.

## Documentation contract

The README "Install" section states both commands: `pip install screamingface` for the
hosted client, and `pip install "screamingface[runtime,notebook]"` for the local stack. A
troubleshooting entry maps `No module named 'X'` during `up` to the missing extra.

## Consequences

- `screamingface prepare` on a plain install now fails with the install command instead of
  working by accident where `datasets` and `nltk` are preinstalled. This is intended:
  every `prepare` dependency ships in the same extra.

## Boundaries

- No dependency, packaging, or public API change.
- No app code changes; only the SDK runtime and README.
- Tests must not require the runtime extra, and must not depend on which modules the host
  happens to have installed.

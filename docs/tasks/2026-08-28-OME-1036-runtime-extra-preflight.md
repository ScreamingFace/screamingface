---
id: OME-1036
linear_url: https://linear.app/openmined/issue/OME-1036/detect-a-missing-runtime-extra-before-the-local-stack-boots-colab-no
status: in_progress
type: bug
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-28
closed:
---

# Detect a missing [runtime] extra before the local stack boots

A user on fresh Colab installed plain `screamingface` (the line the README "Install"
section shows). Part A on the hosted engine worked. `screamingface up` then died during
startup with `SCREAMINGFACE_RUNTIME_ERROR No module named 'tortoise'`, and `status`
showed all three services down.

`require_runtime_extra()` probes five imports. Four come from the wheel itself (the build
hook vendors the app sources, and their `__init__` files import nothing heavy). The fifth,
`uvicorn`, is preinstalled on Colab because gradio needs it. So the guard passes without
the `[runtime]` extra, and the first missing module dies inside the `_serve` child at
`_migrate()`, with no hint to install the extra. `screamingface doctor` calls the same
guard, so it reports the broken state as healthy.

Fix, in layers:

1. Probe the modules only the extra provides and the local boot path needs, with
   `importlib.util.find_spec` (fast; no `litellm` import; runs in CI without the extra).
   Name the missing modules and the install command.
2. Translate an `ImportError` in the `_serve` child into the install hint.
3. Include the last runtime log lines when `_wait_ready` reports a dead child.
4. State both README install lines: plain (hosted client) and `[runtime,notebook]` (local).

Ledger: `docs/work/2026-08-28-OME-1036-runtime-extra-preflight.md`.
Spec: `docs/spec/2026-08-28-OME-1036-runtime-extra-preflight.md`.

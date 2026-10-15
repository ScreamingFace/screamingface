---
ticket: OME-1615
stack: aigateway
status: done
started: 2026-10-15
finished: 2026-10-15
---

# pin-litellm-model-map — the gateway reads litellm's bundled model list, never a download

## Intent

The 2026-10-15 paid smoke press (run 38711531628) went 69 of 70 boards red with `provider_error`.
Every call to the panel's reasoning member, `openrouter/qwen/qwen3.7-flash`, failed in about 37 ms
inside the gateway. Reproduced locally: litellm raised `UnsupportedParamsError: openrouter does
not support parameters: ['reasoning_effort']`. The same call sent straight to OpenRouter, with the
same settings, succeeds. The cause is litellm's model list: litellm downloads it from its GitHub
main branch at import, and that copy now has 0 OpenRouter entries, against 269 in the copy bundled
with our pinned litellm 1.102.1. With no entry, litellm does not know the model reasons.

## Planned changes

- `apps/aigateway/src/aigateway/__init__.py`: set `LITELLM_LOCAL_MODEL_COST_MAP=True` before any
  module imports litellm (set, not defaulted).
- `apps/aigateway/tests/unit/test_litellm_model_map_pinned.py`: fresh-interpreter tests.
- `packages/screamingface/tests/e2e/test_runtime_litellm_model_map.py`: the same incident check
  through the local runtime's boot order, on the `[runtime]` extra's own litellm (1.104.2).
  Added on review (PR #1429, non-blocking follow-ups).

## Test plan

- Importing `aigateway.main` in a fresh interpreter reports a forced local load, with the
  download URL pointed at a closed port so an attempted download would show as a fallback.
- The same with `LITELLM_LOCAL_MODEL_COST_MAP=False` inherited from the environment.
- The incident replayed offline: a local server serves litellm's bundled map with every
  OpenRouter row removed, as the 2026-10-15 download was; the gateway, and the runtime's boot,
  must still know `qwen/qwen3.7-flash` and accept its `reasoning_effort` through litellm's own
  parameter check (`get_optional_params`).

## Acceptance

- Every new test passes with the change and fails without it.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the task mirror.
- **Commits:** see the PR.
- **Gates:** gateway: the 3 new tests pass, and all 3 fail without the `__init__.py` change.
  SDK runtime (`SCREAMINGFACE_TEST_E2E=1`, `--extra runtime`, litellm 1.104.2): the new test
  passes, and fails without the change; outside the lane it skips with its reason. The tests of
  code that reads litellm's model list (request hardening, anthropic and ollama parameter
  projection, openai dispatch, no-enterprise guard): 96 passed; the OpenRouter provider's unit
  tests: 994 passed. ruff, ruff format and pyright clean on the touched files.
- **Deviations:** the first draft's "bundled list knows qwen" test passed without the fix (an
  unreachable download falls back to the bundled list), so it was dropped; review asked for that
  check, and it now runs against a served map without OpenRouter rows, which fails without the
  fix. The runtime boots `aigateway` before its first `import litellm` (`server.py`), so the pin
  covers it with no runtime change.
- **Owner verify:** after deploy, press the paid smoke again; expect the Fusion boards to answer.
  Whether production's gateway restarted after the upstream change was not checked.

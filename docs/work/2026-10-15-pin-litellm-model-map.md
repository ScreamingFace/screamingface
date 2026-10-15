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
- `apps/aigateway/tests/unit/test_litellm_model_map_pinned.py`: two fresh-interpreter tests.

## Test plan

- Importing `aigateway.main` in a fresh interpreter reports a forced local load, with the
  download URL pointed at a closed port so an attempted download would show as a fallback.
- The same with `LITELLM_LOCAL_MODEL_COST_MAP=False` inherited from the environment.

## Acceptance

- Both tests pass with the change and fail without it.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the task mirror.
- **Commits:** see the PR.
- **Gates:** the new tests: 2 passed; without the `__init__.py` change both fail. The tests of
  code that reads litellm's model list (request hardening, anthropic and ollama parameter
  projection, openai dispatch, no-enterprise guard): 96 passed; the OpenRouter provider's unit
  tests: 994 passed. ruff, ruff format and pyright clean on the touched files.
- **Deviations:** dropped a third test that checked the bundled list knows qwen reasons: it
  passed without the fix too (an unreachable download falls back to the bundled list), so it
  tested litellm's data, not our change.
- **Owner verify:** after deploy, press the paid smoke again; expect the Fusion boards to answer.
  Whether production's gateway restarted after the upstream change was not checked.

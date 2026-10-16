---
ticket: OME-1634
stack: aigateway
status: in_progress
started: 2026-10-16
finished:
---

# codex-plan-unsupported — name the ChatGPT plan when Codex refuses every model

## Intent

A Codex sign-in on a **free** ChatGPT plan gets a 400 "model not supported when using Codex with a
ChatGPT account" for every model, and the gateway relays it as a generic `provider_error` carrying
the raw upstream text. Callers cannot tell a plan problem from a bad request. Map that refusal to a
typed 403 `codex_plan_unsupported` that names the plan from the token, with a gateway-authored
message. Spec: `docs/spec/2026-10-16-codex-plan-unsupported.md`.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/codex_provider/plugin.py` — `chat_completion` error mapping
- `apps/aigateway/src/aigateway/plugins/codex_provider/auth.py` — expose the plan claim (reuse `_auth_claims`)
- `apps/aigateway/tests/unit/test_codex_plan_unsupported.py` (new)

## Test plan

See `docs/plan/2026-10-16-codex-plan-unsupported.md`.

## Acceptance

- The plan refusal reaches the caller as 403 `{code: codex_plan_unsupported, provider, model, plan, message}`; no upstream text in it.
- Every other Codex error is unchanged (same status, same `provider_error` detail).
- The credential is not marked errored (Codex keeps the default no-mark hook).
- `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `plugins/codex_provider/{plugin,auth}.py`, new
  `tests/unit/test_codex_plan_unsupported.py` (10 tests).
- **Commits:** see the branch (`fix(aigateway): name the ChatGPT plan when Codex refuses every model`).
- **Gates:** `run_gates.py aigateway` → ALL GATES GREEN.
- **Deviations:** live check of the 403 not run — the throwaway gateway's Codex profile was
  pending a re-sign-in at the time; the unit tests drive `chat_completion` with the exact
  upstream refusal text captured on 2026-10-16.

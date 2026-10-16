---
ticket: OME-1634
stack: aigateway
status: blocked
started: 2026-10-16
finished:
---

# codex-plan-unsupported — typed Codex model refusal + live Codex model list

## Intent

A Codex sign-in on a **free** ChatGPT plan gets a 400 "model not supported when using Codex with a
ChatGPT account" for every model, and the gateway relays it as a generic `provider_error` carrying
the raw upstream text. Callers cannot tell a plan problem from a bad request. Map that refusal to a
typed 403 `codex_plan_unsupported` that names the plan from the token, with a gateway-authored
message. Spec: `docs/spec/2026-10-16-codex-plan-unsupported.md`.

## Amendment (2026-10-16, owner direction: live discovery + renamed refusal)

Live check showed a **plus** plan is refused for every static slug too; the backend's live list is
`gpt-6-astra`, `gpt-5.6-{sol,terra,luna}`. Rename the refusal to `codex_model_unsupported`, add
`available_models` from a per-account live list (`GET /backend-api/codex/models`), and serve that list
through the OME-972 listing port. Spec/plan amended first.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/codex_provider/plugin.py` — `chat_completion` error mapping
- `apps/aigateway/src/aigateway/plugins/codex_provider/auth.py` — expose the plan claim (reuse `_auth_claims`)
- `apps/aigateway/tests/unit/test_codex_plan_unsupported.py` (new)
- amendment: `core/parameter_discovery.py` (`HttpxDiscoveryClient(headers=)`),
  `plugins/codex_provider/live_models.py` (new), tests `tests/unit/codex/test_codex_live_models.py`,
  `tests/unit/test_httpx_discovery_headers.py`

## Test plan

See `docs/plan/2026-10-16-codex-plan-unsupported.md`.

## Acceptance

- The plan refusal reaches the caller as 403 `{code: codex_plan_unsupported, provider, model, plan, message}`; no upstream text in it.
- Every other Codex error is unchanged (same status, same `provider_error` detail).
- The credential is not marked errored (Codex keeps the default no-mark hook).
- `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `plugins/codex_provider/{plugin,auth}.py`, new `plugins/codex_provider/live_models.py`,
  `core/parameter_discovery.py` (`HttpxDiscoveryClient(headers=)`); tests
  `tests/unit/test_codex_plan_unsupported.py` (10, renamed code + message only),
  new `tests/unit/codex/test_codex_live_models.py` (26), new `tests/unit/test_httpx_discovery_headers.py` (3).
- **Commits:** `fix(aigateway): name the ChatGPT plan when Codex refuses every model`;
  `feat(aigateway): read the live Codex model list and type the model refusal`.
- **Gates:** `run_gates.py aigateway --base <merge-base>` → ALL GATES GREEN (append-only base is the
  merge-base because the rename touches this PR's own earlier test, as directed).
- **Live e2e (port 9121, DB copy, plus account):** `codex/gpt-5.4` → 403 `codex_model_unsupported`,
  `plan: plus`, `available_models` = gpt-6-astra, gpt-5.6-sol/terra/luna; `/v1/models` then lists exactly
  those four Codex rows (before: the five dead seeds); runner on `codex/gpt-6-astra`: text READY,
  PNG 4827, PDF ZEBRA-4127 — all 200 and correct.
- **Deviations:** static seed swap NOT done — `tests/unit/test_codex_provider.py` (exact set) and
  `tests/unit/test_plugin_loader.py` (`codex/gpt-5.4-mini`) pin the old slugs; changing them is an
  append-only conflict left to the owner. Until then a cold process lists the dead seeds until the first
  refresh (any refusal) succeeds.

---
ticket: OME-1634
stack: aigateway
status: in_progress
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
  `feat(aigateway): read the live Codex model list and type the model refusal`; merge of
  `origin/main` (OME-1136 screen); `fix(aigateway): keep the Codex model refusal through the OME-1136 error screen`.
- **Merge with OME-1136:** main's screen reads only `error.message`, which dropped the refusal's top-level
  `detail` and silently broke the typed 403 (CI red). `chat_handler` now also reads a short `detail` that
  carries the refusal marker (`tests/unit/codex/test_codex_model_refusal_wire.py`, 3 tests). This PR's own
  "other errors unchanged" test now expects main's screened `provider_error` message (merge resolution).
- **Gates:** `run_gates.py aigateway --base <merge-base>` → ALL GATES GREEN (`--base origin/main` after the
  merge; this PR's own earlier test changed for the rename and the merge resolution).
- **Live e2e (port 9121, DB copy, plus account):** `codex/gpt-5.4` → 403 `codex_model_unsupported`,
  `plan: plus`, `available_models` = gpt-6-astra, gpt-5.6-sol/terra/luna; `/v1/models` then lists exactly
  those four Codex rows (before: the five dead seeds); runner on `codex/gpt-6-astra`: text READY,
  PNG 4827, PDF ZEBRA-4127 — all 200 and correct.
- **Deviations:** static seed swap NOT done — `tests/unit/test_codex_provider.py` (exact set) and
  `tests/unit/test_plugin_loader.py` (`codex/gpt-5.4-mini`) pin the old slugs; changing them is an
  append-only conflict left to the owner. Until then a cold process lists the dead seeds until the first
  refresh (any refusal) succeeds.
- **Review fix (blocking, kill switch):** the refusal path's account-list read ignored
  `AIGW_DISCOVERY_ENABLED=false`. Now `create_app` passes the setting to every plugin via the new
  `configure_discovery(enabled=...)` contract hook (default no-op; a plugin without it is skipped, so
  duck-typed providers and test doubles still load), and Codex disables its `CodexModelDirectory`. A
  disabled directory builds no client and opens no connection, and the 403 omits `available_models`.
  4 appended tests in `tests/unit/codex/test_codex_live_models.py` (zero requests with discovery off,
  re-enable restores the list, and `create_app` wiring for false/true). The spec §2 "Kill switch" bullet
  and the `config.py` comment now describe it. Gates: ALL GATES GREEN. Live e2e on port 9121 with my own DB
  copies: discovery on → 403 with the four live models, and `/v1/models` switches to them. Discovery off →
  403 without `available_models`, and `/v1/models` keeps the seeds. In both modes, gpt-6-astra
  text/PNG/PDF all return 200 and are correct.
- **2026-10-17 security fix (owner-approved):** removed the shared "latest account list" listing
  (cross-tenant entitlement disclosure flagged by the security review); `/v1/models` serves the static
  seeds, swapped to the four current models. Changed PR-local tests that pinned the leak and two
  `main` tests that pinned the dead seeds (`test_codex_provider.py`, `test_plugin_loader.py`), both
  approved by the owner; gates run with `--skip-append-only` for that change only. Live: listing
  identical before/after a refusal; `gpt-5.4` → 403 `codex_model_unsupported` (plan plus, 4
  available); `gpt-6-astra` → 200.

# Spec — Codex model refusal as a typed error + live Codex model list (`OME-1634`)

## Problem

Verified live 2026-10-16:

- The Codex backend refuses a model it does not serve to the signed-in ChatGPT account with
  `400 {"detail":"The '<model>' model is not supported when using Codex with a ChatGPT account."}`.
  A **free** plan gets this for every model; a **plus** plan gets it for every slug in the
  gateway's static catalog (`gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.2`) —
  those slugs are dead.
- `GET https://chatgpt.com/backend-api/codex/models?client_version=0.154.0` (headers
  `Authorization: Bearer <access_token>`, `ChatGPT-Account-Id`, `originator: codex_cli_rs`)
  answers `{"models":[{slug, visibility: "list"|"hide", supported_in_api, input_modalities}]}`.
  Today `visibility=list`: `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`.
- The gateway relays the refusal as a generic 400 `provider_error` with the raw upstream text.

## Behaviour

### 1. Typed refusal `codex_model_unsupported`

When the Codex upstream answers **400** and its **top-level `detail`** (a short string) contains
`not supported when using Codex with a ChatGPT account`, the plugin raises:

    403 {"code": "codex_model_unsupported",
         "provider": "codex",
         "model": "<model as requested>",
         "plan": "<chatgpt_plan_type from the access token, or 'unknown'>",
         "message": "<gateway-authored, names the model and the plan>",
         "available_models": ["codex/<slug>", ...]}   # only when the account's list is known

- **403, not 400:** the request is well-formed; the account's entitlement refuses this model.
- **No credential marking:** Codex keeps the default `should_mark_profile_error_on_dispatch_status`
  (`False`); the profile stays authenticated.
- **Plan from the token** (`https://api.openai.com/auth` → `chatgpt_plan_type`, no signature check —
  display only). Missing → `unknown`.
- **No upstream text** in the detail.
- `available_models` comes from the account's live list (section 2), fetched with the **caller's own
  credential** on this error path. Unknown (no account id, fetch failed, empty) → key omitted; the
  403 itself never depends on discovery succeeding.
- **Trusted carrier only (PR #1441 review, 2026-10-20):** the top-level `detail` is the one
  refusal carrier. `chat_handler` reads it before `error.message` and relays it in its own
  `{"detail": ...}` shape; the plugin classifies only that shape. The marker inside an
  `error.message` (plain, or mimicking the detail shape — the latter is withheld) never re-types
  an ordinary 400 and triggers no model-list read.
- **Plan bound:** the unsigned claim is named only when it is a short lowercase identifier
  (`[a-z][a-z0-9_-]{0,31}`); anything else → `unknown`.
- Every other error keeps today's mapping exactly.
- Renamed from the earlier draft `codex_plan_unsupported`: a plus plan is refused per model too, so
  "plan unsupported" mis-names the common case.

### 2. Live Codex model list

Reuses the OME-972 machinery (`ObservationCache`, `fetch_discovery_json` bounds, `DiscoveryError`
vocabulary, `ModelDiscoverySource` + `discover_live_models` port read by `ModelCatalog`).

**Decision — the list is per ChatGPT account, the listing port is process-wide.** The endpoint needs
a bearer token and answers per account; `ModelDiscoverySource` / `discover_live_models` take no
credential and serve one process-wide snapshot. Resolution:

- A plugin-local `CodexModelDirectory` caches the list **per ChatGPT account id** (`ObservationCache`,
  TTL 300 s, stale 3600 s, failure 30 s). It dials only with a credential handed to it by a dispatch
  — today the refusal path — never by enumerating stored profiles (no cross-tenant credential reads,
  no plugin access to the profile index).
- **Revised 2026-10-17 (security review on PR #1441):** the shared listing does **not** serve any
  account's list. A Codex list is an account's entitlement (which models its ChatGPT plan unlocks),
  and `/v1/models` is one process-wide listing, so serving "the most recently refreshed account's
  list" disclosed one tenant's entitlements to every other tenant. The plugin declares **no**
  `model_discovery_source`; `/v1/models` lists the static seeds (`models.py`), now the backend's
  current listed models (`gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`). An account's
  live list is returned only to that account's own refusal (`available_models`). Regression test:
  account A refreshes, the shared listing still shows only the seeds.
- Only `visibility == "list"` slugs are published. Strict parse, fail closed (all-or-nothing):
  malformed envelope/row → `malformed_json`; zero listed → `model_catalog_empty`; over 200 →
  `model_catalog_too_large`. A failure never evicts the last good list.
- Transport: the bounded `HttpxDiscoveryClient` gains an optional constructor `headers` mapping. The
  app-lifetime runtime client is still built without headers, so the injected discovery client stays
  credential-free; only the Codex plugin builds a per-call client carrying the caller's own token.
  Core still imports no plugin.
- **Kill switch.** `AIGW_DISCOVERY_ENABLED=false` silences this read too: `create_app` hands the
  setting to every plugin through the `configure_discovery(enabled=...)` contract hook (default
  no-op), and the Codex plugin disables its `CodexModelDirectory`. A disabled directory builds no
  client and opens no connection; the refusal stays a 403 with `available_models` omitted, and the
  listing falls back to `register_models()` (the catalog is absent anyway). This keeps the gateway
  invariant that the switch audits to zero discovery egress of any kind.

### 3. Static fallback

The static `register_models()` slugs were dead; they are now the four live slugs (`gpt-6-astra`,
`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`). **Owner-approved 2026-10-17** (Sergey, working
session): the seed swap and the matching edits to the two `main` tests that pinned the old slugs
(`tests/unit/test_codex_provider.py` exact set, `tests/unit/test_plugin_loader.py`
`codex/gpt-5.4-mini`). `/v1/models` is process-wide and always serves these seeds; no account's
live list ever enters it (section 2).

## Out of scope

- Warming the list on successful dispatches or at sign-in.
- Refusing a free-plan sign-in at OAuth time.
- Changing the generic `provider_error` mapping.

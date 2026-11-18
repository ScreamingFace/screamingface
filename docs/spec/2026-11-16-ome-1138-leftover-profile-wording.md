---
status: approved   # owner, 2026-11-16
issue: OME-1940, OME-1941   # gateway, SDK; both under OME-1138
parent: OME-1138
date: 2026-11-16
---

# OME-1138 follow-up — retire the leftover Profile wording

## 1. Why

Profiles are gone from the gateway (OME-1138, closed 2026-11-16). The close review found Profile
wording that the close-out did not cover:

- L5 renamed identifiers and the admission messages only (close-out spec §4.5). It left the
  provider plugins' credential errors, which still say "profile" and send the caller to the
  retired desktop app ("Re-authenticate via Electron"). The Gemini 401 also still asks for "an
  OAuth profile, a profile API key".
- About 25 comments and docstrings in gateway src still describe Profiles as a live concept.
- L4b removed `ORMStore.mutate`, but eight gateway test doubles still define a `mutate` that
  nothing calls (the follow-up recorded on `OME-1798`).
- An SDK test fixture still sends the model-parameter scope `account_profile`. Since L6 the
  gateway sends `account_connection`.

## 2. Scope

### 2.1 Gateway messages (leaf 1, `aigateway`)

| Where | Today | After |
|---|---|---|
| `plugins/{anthropic,antigravity,codex,gemini}_provider/auth.py`, `CredentialNotFoundError` | `No tokens for <provider> profile '<name>'. Re-authenticate via Electron.` | `No tokens for <provider> credential '<name>'. Reconnect the provider.` |
| the same four files, `ReauthRequiredError` | `Refresh token rejected for profile '<name>' (HTTP <status>). Re-auth required.` | `Refresh token rejected for credential '<name>' (HTTP <status>). Re-auth required.` |
| `plugins/gemini_provider/chat_handler.py:166`, 401 | `Gemini requires an OAuth profile, a profile API key, or GEMINI_API_KEY/GOOGLE_API_KEY` | `Gemini requires a connected OAuth or API-key credential, or GEMINI_API_KEY/GOOGLE_API_KEY` |

Nothing in the repository parses these texts. No test pins them today.

### 2.2 Gateway comments (leaf 1)

Rule: a comment that describes Profiles as present changes. A comment that names a retired
stage, the retired routes, saved defaults, or why a migrated Connection addresses the legacy
Profile blob stays: it is history, and it is still true.

The comments that change, under `apps/aigateway/src/aigateway/`:

- `core/auth/cloudflare_identity.py:17`: "profiles" in the list of what works downstream;
- `core/auth_types.py:1,12`: "shared by Profiles, Connections …", "Profile or OAuthConnection";
- `core/credential_strategy_cache.py:27`: "same-named profiles";
- `core/plugin_base/_ports.py:111,115,119`: "for this profile";
- `core/plugin_base/_provider.py:98,221,253,318`;
- `core/request_hardening.py:5`: "before profile lookup";
- `core/secrets/local.py:21`: "profile-id lists";
- the identity lists "no account, profile, user, …" in `core/request_cache/global_eligibility.py:15`,
  `global_keys.py:12`, `global_plan.py:19,27`, `tavily_retrieval.py:14`,
  `plugins/openai_provider/runtime_guard.py:208` and `routes/chat_cache_stage.py:398`;
- `plugins/codex_provider/plugin.py:73,233` and `live_models.py:12`;
- `plugins/gemini_provider/chat_handler.py:49`: "Per-profile API key";
- `plugins/huggingface_provider/plugin.py:78` and `plugins/openrouter_provider/plugin.py:141`;
- `plugins/openai_provider/settings.py:130`;
- `routes/chat_dispatch.py:387,389` and `routes/model_admission.py:18`.

### 2.3 Gateway test doubles (leaf 1)

Delete the unused `mutate` from the doubles in `tests/unit/anthropic/test_anthropic_auth.py`,
`antigravity/test_antigravity_auth.py`, `codex/test_codex_auth.py`, `gemini/test_gemini_auth.py`,
`huggingface/test_huggingface_provider.py`, `remote_endpoint/test_origin_binding.py`,
`remote_endpoint/test_plugin.py` and `test_api_key_strategy.py`. No test assertion changes.
`_pg_mvcc_store.MvccRowStore.mutate` stays: `test_connection_delete_set_race.py` calls it.

### 2.4 SDK fixture (leaf 2, `client-sf`)

`packages/screamingface/tests/test_hosted_byom_preflight.py:53`: `account_profile` becomes
`account_connection`. The SDK passes the scope through as opaque text, so no behaviour changes.

## 3. Out of scope

- The R3 error codes, the 410 shells, `x_profile_unsupported` and the wire headers
  `X-AIGW-Gemini-Profile` and `X-AIGW-Antigravity-Profile` (close-out spec §2, "Keep").
- The providers' OAuth `profile` scopes, the "cost profile" in `tracing.py`, and
  `routes/saved_defaults_refusal.py`, which names the retired feature on purpose.
- Test docstrings and `MvccRowStore.mutate`.
- `routes/credits.py`, which refuses `X-Profile` with a plain 400 (#1753, outside this epic).

## 4. Acceptance

- The four plugins' errors and the Gemini 401 read as in §2.1. New tests pin them, and they
  fail before the change.
- The §2.2 comments no longer describe Profiles as present; the kept history is unchanged.
- No gateway test double defines `mutate` except `MvccRowStore`.
- `run_gates.py aigateway` and `run_gates.py screamingface` pass. The approved test changes
  are recorded in `.claude/test-change-approvals/`.
- One PR with both leaves, like L6 (#1613). The gateway release note lists it under Bug Fixes.

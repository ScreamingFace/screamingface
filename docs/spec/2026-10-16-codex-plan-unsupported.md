# Spec — Codex plan refusal as a typed error (`OME-1634`)

## Problem

Root cause of `OME-1634` (2026-10-16): the gateway's Codex sign-in was on a ChatGPT **free** plan
(`chatgpt_plan_type: free` in the token), while the working `codex` CLI used a **plus** account. The
Codex backend refuses every model for a free plan:

    400 {"detail":"The '<model>' model is not supported when using Codex with a ChatGPT account."}

`CodexProviderPlugin.chat_completion` turns every `CustomLLMError` into
`HTTPException(status, {"code": "provider_error", "message": <raw upstream text>})`. The caller sees
a 400 that reads like a bad request, and the gateway leaks provider text.

## Behaviour

When the Codex upstream answers **400** and its text contains
`not supported when using Codex with a ChatGPT account`, the plugin raises:

    403 {"code": "codex_plan_unsupported",
         "provider": "codex",
         "model": "<model as requested>",
         "plan": "<chatgpt_plan_type from the access token, or 'unknown'>",
         "message": "This ChatGPT account (plan: <plan>) cannot use Codex models. Sign in with a ChatGPT plan that includes Codex."}

- **403, not 400:** the request is valid; the credential's entitlement refuses it. Not retryable.
- **No credential marking:** Codex does not override `should_mark_profile_error_on_dispatch_status`
  (default `False`), so the profile stays authenticated. Upgrading the plan or signing in again fixes it.
- **Plan from the token:** decoded from the bearer access token's `https://api.openai.com/auth`
  claims (no signature check — display only, never an authorization decision). Missing → `unknown`.
- **No upstream text** in the new detail (gateway-authored message only).
- Every other error keeps today's mapping exactly.

## Out of scope

- Warning or refusing a free-plan sign-in at OAuth time.
- Changing the generic `provider_error` mapping or the Codex model catalog.

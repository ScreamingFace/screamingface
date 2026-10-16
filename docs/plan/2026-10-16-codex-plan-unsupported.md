# Plan — Codex plan refusal as a typed error (`OME-1634`)

Spec: `docs/spec/2026-10-16-codex-plan-unsupported.md`. Stack: aigateway (sdlc-python, TDD).

1. **RED** `tests/unit/test_codex_plan_unsupported.py`, driving `CodexProviderPlugin.chat_completion`
   with the handler patched to raise `CustomLLMError`:
   - plan-refusal 400 + token with `chatgpt_plan_type: free` → 403 detail exactly as specified, `plan == "free"`;
   - same refusal, token without the claim / not a JWT → `plan == "unknown"`;
   - the new detail never contains the upstream text;
   - a different 400 (other text), a 429 and a 502 → unchanged `provider_error` with today's status and message;
   - a plan-refusal text on a non-400 status → unchanged (match needs both);
   - plugin keeps `should_mark_profile_error_on_dispatch_status(403) is False`.
2. **GREEN** `auth.py`: `plan_type_from_token(token) -> str | None` over `_auth_claims`.
   `plugin.py`: in the `except CustomLLMError` branch, check status + marker text, build the typed 403.
3. **Gates** `run_gates.py aigateway`.
4. **PR** `Refs: OME-1634` (bug already filed); branch `OME-1634-codex-plan-unsupported`.

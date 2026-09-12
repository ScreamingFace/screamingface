# OME-1042 — provider access before evaluation

## Required behavior

Before dispatching any Recipe evaluation Candidate, reject authoritative missing
access to a required provider with ProviderConnectionError and an actionable hint.
Support both Clients. Preserve valid local BYOK, hosted profiles, and supported
profileless access. Discovery failures retain their own diagnostics. This check
does not validate credentials by making an inference request.

## Current gap

At c1c92562, the evaluation runner checks model admission and explicit parameters,
but not provider access. Neither existing discovery surface is sufficient:

- Gateway model_parameters.py publishes datasheets without stored credentials
  after OME-1167; a successful details lookup does not prove access.
- Engine connections/aigateway.py reports stored connection rows or hosted
  profile states. Missing rows become not_connected.
- Gateway gemini_provider/plugin.py permits profileless dispatch and selects
  api_key when its environment key exists. The existing test
  tests/unit/gemini/test_gemini_routes.py::test_gemini_chat_allows_no_profile_when_env_key_exists
  protects that behavior. A Client check based on not_connected would reject it.

## Proposed boundary

Gateway owns credential-target resolution and should expose a secret-free,
no-inference access check using that same policy. Engine forwards caller/profile
context and the result. Client consumes the result before Candidate dispatch.
Do not copy provider-specific environment or credential rules into the Client.

## Decision pending

Expand the implementation across the three landings with separate linked units,
instead of implementing an incorrect Client-only connection-list check.

---
ticket: OME-307
stack: aigateway
status: done
started: 2026-07-21
finished: 2026-07-23
reopened: 2026-07-22
---

# OME-307 - API-key validation with actionable states

## Intent

Validate Anthropic, Gemini, Hugging Face and enabled OpenRouter API keys before AIGateway stores or
activates them. Return provider-neutral actionable states while preserving account-scoped encrypted
credential storage and existing OAuth behavior.

## Delivered behavior

- Added provider-neutral validation domain types, orchestration and a bounded direct-HTTP transport.
  Requests use fixed HTTPS endpoints, refuse redirects and compressed responses, ignore ambient
  proxy configuration, enforce response and wall-clock limits, and never log or persist candidate
  secrets.
- Added provider-local validators for Anthropic, Gemini, Hugging Face and OpenRouter. A key becomes
  `valid` only after both authentication and a minimal readiness probe succeed. Provider responses
  map to stable actionable outcomes rather than leaking provider-specific payloads.
- Added a non-persisting validation endpoint and applied the same validation service to connection
  creation, connection replacement and profile API-key publication. Every covered writer validates
  before its first durable side effect.
- Added all-status OAuth connection label checks without changing the database schema.
- Hardened Gemini and Hugging Face probe selection against retired or gated defaults, and preserved
  OpenRouter's explicit internal free-model default.
- Hardened nested JSON, slow-stream, malformed-response and transport-failure handling. Validation
  failures preserve prior credentials, profile metadata and cache state.

## Lifecycle and concurrency guarantees

- Connection replacement re-checks eligibility after external validation and publishes the
  credential plus conditional reactivation inside one short transaction.
- Connection deletion publishes credential deletion plus revocation atomically, so an older
  validation request cannot restore a deleted connection.
- OAuth profile completion transitions only a pending profile and publishes credential plus profile
  metadata atomically. API-key publication uses the same credential/profile transaction boundary.
- A late OAuth callback cannot replace a newer API-key publication; conflicts return a retryable
  `409 profile_auth_conflict` rather than exposing mixed state.
- Cancellation, replacement, delete/recreate and external same-key ABA scenarios have deterministic
  regression coverage. No schema or migration change was required.

## Verification

- Focused lifecycle, validation, chat and token suites: **245 passed**.
- PostgreSQL lifecycle and migration suites: **5 passed**.
- Final AIGateway quality gate: Ruff, format, Pyright, enterprise-import guard, full non-live pytest
  suite and coverage threshold all passed.
- PR checks passed on Python **3.12** and **3.13**, including CI cost checks.
- Approved regression-test updates replaced assumptions invalidated by the new atomic publication
  boundary; no gate logic was weakened.

## Outcome

- **Implementation commits:**
  - `85a7d9c8` - `feat(aigateway): add actionable API key validation`
  - `97bb8d36` - `fix(aigateway): harden validation and refresh races`
- **Merged:** PR [#420](https://github.com/ScreamingFace/screamingface/pull/420), merge commit
  `66deae0a`, on 2026-07-23.
- **Scope:** 59 files, 8,536 insertions and 488 deletions across validation core, provider adapters,
  routes, lifecycle stores and focused regression coverage.
- **Linear:** OME-307 completed on 2026-07-23.

## Residual scope

Manual profile/connection refresh racing with deletion remains a separately approved follow-up.
Live provider-drift diagnostics remain opt-in and are not part of the deterministic merge gate.

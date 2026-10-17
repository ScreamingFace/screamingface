---
ticket: OME-1499
status: implemented
date: 2026-10-16
spec: ../spec/2026-10-16-OME-1499-local-model-fusion.md
provenance: retrospective reconstruction after implementation
---

# OME-1499 implementation plan

This plan records the implementation sequence retrospectively. It is a closeout and review aid, not
evidence that the repository's preferred spec → plan → code order was followed for OME-1499.

## Phase 1 — AIGateway provider

- Add a bundled `local_provider` discovered through the standard module-level `PLUGIN` convention.
- Validate numeric loopback `/v1` settings and expose bounded model discovery.
- Dispatch non-streaming chat directly through HTTPX with no auth, redirects, or environment proxy.
- Declare only proven parameters and fail closed on unsupported request controls.
- Preserve reasoning/content/tool-call response evidence under bounded JSON validation.

## Phase 2 — Engine executable overlay

- Mirror routeable `local/*` and `ollama/*` rows into an atomic process-local snapshot.
- Project raw IDs to URL4 route IDs and decode them only at Gateway request boundaries.
- Inject the snapshot into local in-process run environments; hosted composition remains unchanged.
- Refresh through the existing caller-scoped catalog cache before cold details and run-world creation.
- Preserve catalog byte contracts when rewriting only the public `model.id` route token.

## Phase 3 — Fusion and benchmark proof

- Run local and Ollama models as three Fusion members plus model synthesizer on current MEDXPERT.
- Assert operation evidence, score, coverage, and raw/route identity behavior.
- Add a process E2E with a deterministic local model server plus real AIGateway, Engine, and SDK.
- Prove the E2E works without a preliminary model-list request and cleans every process on failure.

## Phase 4 — pre-PR hardening

- Forward async-generator close through `_PreparedExecutor`.
- Mark dynamic local routes as `web_search=False` until the provider proves tool support.
- Preserve retryable upstream statuses while sanitizing bodies.
- Warn when local overlay is disabled by a nonnumeric Gateway address.
- Make the opt-in live harness fail on missing prerequisites and require an explicit chat model.
- Run all affected stack gates and independent adversarial review before push.

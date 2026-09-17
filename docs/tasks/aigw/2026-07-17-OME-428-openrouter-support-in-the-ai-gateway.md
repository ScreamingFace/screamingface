---
id: OME-428
linear_url: https://linear.app/openmined/issue/OME-428/ome-428-openrouter-support-in-the-ai-gateway
status: in_progress
type: Feature
priority: High
labels: [aigateway]
created: 2026-07-13
closed:
---

# OME-428 - OpenRouter support in the AI Gateway

Add first-class OpenRouter support and a provider-neutral credential-mode contract in two
independently releasable checkpoints.

## Checkpoint A - local BYOK

**Status: done.**

- Disabled-by-default OpenRouter provider discovered through the existing provider registry.
- Account-scoped API-key connections use the existing encrypted credential store; no new schema,
  migration, secret backend, or dependency was added.
- Non-streaming chat dispatch uses the pinned official OpenRouter API base, validated
  `openrouter/<author>/<model>` IDs, and gateway-owned attribution headers.
- Shared ingress strips caller-controlled routing, credentials, retries, fallbacks, logging,
  callbacks, telemetry destinations, and message-redaction controls before provider dispatch.
- OpenRouter errors are sanitized without raw provider text. Only positive HTTP transport evidence
  can retry; converter/body and ambiguous errors are non-retryable. Unknown exceptions return a
  fixed 502, and only a proven 401 invalidates the selected connection.
- `Retry-After` supports unsigned ASCII integer delta-seconds with bounded retries and total wait.
- Native usage, cost, generation identifiers, and BYOK metadata remain available to callers.

Validation: focused security/error suite `131 passed`; full non-live suite `1020 passed, 29
skipped` without warnings; lint, formatting, type checking, enterprise-import guard, append-only
test check against `main`, and coverage threshold all passed.

Live OpenRouter smoke testing is owner-gated and remains required before broad BYOK release, but is
not a merge gate for Checkpoint A.

## Checkpoint B - hosted OpenRouter

**Status: pending.**

- Add the shared `local_byok | hosted_shared` credential-mode contract.
- Guard hosted credential routes and provide deployment-managed OpenRouter credentials.
- Add hosted admission/policy and deployment secret wiring.

Hugging Face support remains owned by OME-394.

Implementation record:
`docs/work/aigw/2026-07-17-OME-428-openrouter-byok-checkpoint-a.md`.

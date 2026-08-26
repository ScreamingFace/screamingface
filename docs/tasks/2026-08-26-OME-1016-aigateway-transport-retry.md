---
ticket: OME-1016
stack: screamingface-engine
status: in_progress
started: 2026-08-26
labels: [screamingface-engine]
actor: agentic
who-acts: agent
---

# OME-1016 — Retry aigateway transport failures in benchmark grading

## Context

Follow-up to OME-993 (grading-error propagation). A transient `httpx.ReadError`
on the runner→aigateway hop during a judge call bypasses the declared `retry=`
policy (only `Url4Error` is retried), carries no error `code`, and renders as
the opaque `draco_grading_failed` fallback with the useless message
`ReadError('')`. Concurrent judge calls that fail together retry in lockstep.

**Constraint: `packages/url4` is untouchable (agnosticism).** All changes live
in the screamingface-engine connector.

## Scope

- **Connector:** retry `httpx.TransportError` with exponential backoff + jitter
  (bounded, module constants), then raise
  `ResolutionError(code="aigateway_transport_error", permanent=False)` with a
  non-empty message, so the report names the real cause and `retryable=true`.
- **Tests:** connector translation + retry-then-succeed; grading-integrity
  retry/exhaustion.

## Out of scope

- `packages/url4` (agnosticism constraint).
- Changing `retry=2` / `retry=JUDGE_RETRIES` counts (would bump the protocol
  revision and invalidate seeded cache keys).
- Changing `on_error="fail"` fan-outs (OME-924) or the collect boundary.
- aigateway-side or SDK-side changes.

## Definition of done

- Judge transport failure is retried (connector backoff); exhaustion renders
  `aigateway_transport_error` + `retryable=true` + non-empty message.
- `packages/url4` untouched; protocol text unchanged.
- `screamingface-engine` gates green.

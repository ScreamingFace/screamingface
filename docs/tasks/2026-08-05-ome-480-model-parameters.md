---
id: OME-480
linear_url: https://linear.app/openmined/issue/OME-480/the-sf-engine-should-expose-all-the-params-offered-by-the-model
status: in_progress
type: feature
priority:
labels: [screamingface-engine, url4-cloud, autonomous, agentic]
created: 2026-08-05
closed:
---

# OME-480 — expose AI Gateway model details through the Engine

The Client talks to the Engine, not directly to AI Gateway. AI Gateway already owns the
profile-bound `GET /v1/model-parameters?model=...` contract; this unit exposes that document
through URL4 Cloud for the same verified identity and profile used by execution.

## Scope

- Add `GET /v1/model-parameters?model=...` to URL4 Cloud.
- Forward `X-User-Email` and `X-Profile` through the existing identity boundary.
- Preserve AI Gateway's successful v1 document without defining another parameter schema.
- Keep success and caller-facing errors private and uncacheable.
- Fail loudly when AI Gateway is unconfigured, unavailable, or returns an unusable contract.

## Out of scope

- SDK model details and preflight (`OME-481`).
- Any AI Gateway, provider-policy, URL4, or Benchmark change.

Spec: `docs/spec/2026-08-05-OME-480-model-parameters.md`

Plan: `docs/plan/2026-08-05-OME-480-model-parameters.md`

Ledger: `docs/work/2026-08-05-OME-480-model-parameters.md`

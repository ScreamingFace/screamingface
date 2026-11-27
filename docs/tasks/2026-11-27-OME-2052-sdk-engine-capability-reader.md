---
id: OME-2052
linear_url: https://linear.app/openmined/issue/OME-2052/read-engine-capabilities-before-gated-submissions
status: In Review
type: task
priority: high
labels: [client-sf, autonomous, agentic]
parent: OME-1306
created: 2026-11-27
closed:
---

# Read Engine capabilities before gated submissions

Add the dormant SDK side of Unit 6 capability negotiation. The Client strictly reads the Engine's
`engine-capabilities-v1` document once for each capability-requiring submission and refuses missing,
malformed, or insufficient discovery before model lookup, token mint, run registration, execution,
or follow.

Capability-free evaluation, raw URL4, named-profile `route_answer`, replay, follow, and result reads
remain request-identical and make no capability request. This leaf adds no public `sf.Router`,
required-ID derivation, capability activation, Engine/Gateway behavior, export, dependency, lock,
chart, or CI change.

Spec: `docs/spec/2026-11-16-router-recipe-extension/` C12.
Plan: `docs/plan/2026-11-16-router-recipe-extension.md` sections 9, 10, and 16.
Ledger: `docs/work/2026-11-27-sdk-engine-capability-reader.md`.
Branch: `OME-2052-sdk-engine-capability-reader`.

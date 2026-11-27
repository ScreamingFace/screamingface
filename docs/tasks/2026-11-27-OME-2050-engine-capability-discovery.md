---
id: OME-2050
linear_url: https://linear.app/openmined/issue/OME-2050/serve-dormant-engine-capability-discovery
status: In Review
type: task
priority: high
labels: [screamingface-engine, autonomous, agentic]
parent: OME-1306
created: 2026-11-27
closed:
---

# Serve dormant Engine capability discovery

Add the Unit 6 capability reader before any Router writer is exposed. The Engine serves the closed
`engine-capabilities-v1` document at `GET /v1/capabilities`, with an empty capability list,
`Cache-Control: private, no-store`, no validator, and no run-token or external I/O requirement.

The release remains dormant: configuration accepts only an empty list and refuses malformed,
duplicate, unknown, or future capability IDs. The route uses the existing App composition and world
mount-collision guard. No capability activation, public Router writer, SDK, Gateway, chart, storage,
worker, dependency, or hosted-readiness change is included.

Spec: `docs/spec/2026-11-16-router-recipe-extension/` C12.
Plan: `docs/plan/2026-11-16-router-recipe-extension.md` sections 9 and 16.
Ledger: `docs/work/2026-11-27-engine-capability-discovery.md`.
Branch: `OME-2050-engine-capability-discovery`.

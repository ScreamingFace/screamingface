---
id: OME-1449
linear_url: https://linear.app/openmined/issue/OME-1449/remove-the-retired-profile-selector-carrier-from-engine-runtime
status: in_progress
type: task
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1138
related: [OME-1381, OME-1394, OME-1398]
blocked_by: []
created: 2026-10-01
closed:
---

# Remove the retired Profile selector carrier from Engine runtime

Stage D already refuses every nonblank `X-Profile` at Engine and AIGateway ingress. This final
carrier landing removes the now-dormant internal selector path from scheduling, queue and process
environments, request scope, and outbound AIGateway requests.

## Owner disposition

On 2026-10-01 the owner confirmed that no legacy queue messages carrying `AIGATEWAY_PROFILE`
remain and authorised full carrier removal in one landing. This is an owner-provided disposition,
not a production census claim.

## Acceptance

- `JobRunner.schedule` and its implementations have no `profile` argument.
- Runtime source contains no `AIGATEWAY_PROFILE` queue or environment contract.
- Runner, catalog, connection and world paths never emit `X-Profile`.
- Every Engine ingress keeps the value-free `400 x_profile_unsupported` refusal.
- Identity, trace, cache policy, answer seed and client-version propagation remain unchanged.
- The full ScreamingFace Engine quality gate passes.

## Non-goals

- D18 pair-addressed admin successor (`OME-1375`).
- Production migration readiness (`OME-1333`).
- AIGateway Profile API and storage retirement (`OME-1209`).

## Implementation status

Implementation, review and local quality gates are complete on `OME-1449-remove-profile-carrier`.
The issue remains in progress until the coordinated landing is merged.

---
id: OME-1394
linear_url: https://linear.app/openmined/issue/OME-1394/aigateway-reject-explicit-x-profile-after-engine-producer-off
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-09-28
closed:
---

# OME-1394 — AIGateway rejects explicit X-Profile

## Outcome

Activate the accepted Stage D AIGateway selector sunset after Engine producer-off: selector-less
requests retain their behavior, while every explicit `X-Profile` is rejected without disclosing its
value.

## Scope

- Chat completions, model parameters, model admission, and provider-access availability.
- Value-free `x_profile_unsupported` HTTP 400 rendering.
- Selector-free `connection_ambiguous` guidance.
- Retire `X-Profile` from response `Vary` where it no longer selects behavior.

## Gate

Offline implementation and verification may proceed. Merge and deployment activation remain
blocked on the approved quick alpha drain proof after Engine build `df6e9b92`.

## Implementation Status

Ready for re-review. Duplicate-header handling, pre-cache refusal, selector-less ambiguity,
target-local invalidation, value-free exceptions, current documentation, and opt-in live callers
are pinned. The complete AIGateway gate runner is green. No deployment or production access was
performed.

## Out Of Scope

- Production/deployment access and the drain proof itself.
- URL4, Engine, SDK, D18, Stage E, schemas, migrations, and dependencies.

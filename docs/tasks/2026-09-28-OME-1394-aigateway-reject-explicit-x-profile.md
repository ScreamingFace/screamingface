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

Activate the accepted Stage D AIGateway selector sunset after Engine producer-off: every explicit
`X-Profile` is rejected without disclosing its value. Selector-less behavior remains unchanged except
for the owner-approved breaking cohort: every pair with multiple active Connections returns `409`,
including a window-era `[default, backup]` pair that previously auto-selected `default`.

## Scope

- Chat completions, model parameters, model admission, and provider-access availability.
- Value-free `x_profile_unsupported` HTTP 400 rendering.
- Selector-free `connection_ambiguous` guidance.
- Retire `X-Profile` from response `Vary` where it no longer selects behavior.

## Gate

Offline implementation and verification may proceed. Merge and deployment activation remain blocked
after Engine build `df6e9b92` until both checks pass:

- the approved quick alpha drain proof for old ingress pods, legacy queued/in-flight/redelivered
  `AIGATEWAY_PROFILE` work, and ambient worker `AIGATEWAY_PROFILE`;
- a separately authorized privacy-safe upper-bound count of unmigrated pairs with multiple active
  Connections and an active `default` label; a nonzero result requires owner disposition or explicit
  impact acceptance.

This issue does not authorize the production read.

## Implementation Status

Ready for re-review. Duplicate-header handling, pre-cache refusal, selector-less ambiguity,
target-local invalidation, value-free exceptions, current documentation, and opt-in live callers
are pinned. The complete AIGateway gate runner is green. No deployment or production access was
performed.

The PR must use title `feat(aigateway)!: reject explicit profile selectors` and include:

`BREAKING CHANGE: AIGateway rejects every nonblank X-Profile and selector-less pairs with multiple active Connections now return 409 even when one Connection is labelled default.`

The selector refusal intentionally runs before chat body parsing and `_aigw` accounting. Its 400
therefore carries no `_aigw` metadata; authentication still runs first. This preserves the
no-body/cache/credential-I/O boundary and keeps the rejected value outside accounting and telemetry.

## Out Of Scope

- Production/deployment access and the drain proof itself.
- URL4, Engine, SDK, D18, Stage E, schemas, migrations, and dependencies.
- Stale AIGateway UI copy, generated schema, and identity diagrams; tracked by `OME-1398`.

---
id: OME-1394
linear_url: https://linear.app/openmined/issue/OME-1394/aigateway-reject-explicit-x-profile-after-engine-producer-off
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-09-28
closed: 2026-10-01
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

Owner waiver recorded 2026-09-29 on `OME-1401`: merge may proceed through normal review and CI
without the alpha drain proof or multi-active/default-label census. No production or cluster read was
performed and no zero-count claim is made. The owner accepts residual fail-closed `400`/`409` risk for
alpha-canary activation. An unexpected increase triggers rollback to Gateway selector honoring while
Engine remains producer-off. `OME-1401` is canceled as waived and no longer blocks this issue.

## Implementation Status

Merged in PR #1114 as `3083640b` on 2026-09-30. Duplicate-header handling, pre-cache refusal,
selector-less ambiguity, target-local invalidation, value-free exceptions, current documentation,
and opt-in live callers are pinned. All required checks passed. No deployment or production access
was performed.

The PR used title `feat(aigateway)!: reject explicit profile selectors` and included:

`BREAKING CHANGE: AIGateway rejects every nonblank X-Profile and selector-less pairs with multiple active Connections now return 409 even when one Connection is labelled default.`

The selector refusal intentionally runs before chat body parsing and `_aigw` accounting. Its 400
therefore carries no `_aigw` metadata; authentication still runs first. This preserves the
no-body/cache/credential-I/O boundary and keeps the rejected value outside accounting and telemetry.

## Out Of Scope

- Production/deployment access and the drain proof itself.
- URL4, Engine, SDK, D18, Stage E, schemas, migrations, and dependencies.
- Stale AIGateway UI copy, generated schema, and identity diagrams; tracked by `OME-1398`.

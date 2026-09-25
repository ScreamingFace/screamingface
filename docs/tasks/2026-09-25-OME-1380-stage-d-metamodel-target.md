---
id: OME-1380
linear_url: https://linear.app/openmined/issue/OME-1380/describe-the-stage-d-selector-sunset-target-in-the-aigateway-metamodel
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
blocked_by: []
created: 2026-09-25
closed: 2026-09-25
---

# Describe the Stage D selector sunset target in the AIGateway metamodel

Catalog-only landing in `screamingface-design` that must merge before Stage D census
instrumentation or runtime changes. Version-bump the cards that describe `X-Profile`,
`AIGATEWAY_PROFILE` or `JobRunner.schedule(profile=...)` and add a "Stage D target, not live"
section carrying the `OME-1377` decisions: unchanged `X-User-Email` identity, selector-less
`(account, provider)` resolution, a value-free non-retryable 400 for every nonblank selector, the
refusal scope, the multi-Connection 409 guidance, and the two-phase rollout with its rollback
floor. No new entities, no `supersedes`, no history rewrite.

## Progress

- 2026-09-25: filed and started against design `main` `1de95b5`.
- 2026-09-25: target committed as `0e071dd`: `product/aigateway/component/provider-access`
  v6 carries the full Stage D target; pointer sections on `protocol/chat-processing` v4,
  `protocol/chat-streaming` v4, `protocol/model-discovery` v3, `component/parameter-contracts` v4,
  `protocol/provider-access` v4, `protocol/provider-credential-admin` v5, `product/engine` v4,
  solution `protocol/completions` v8, `protocol/model-catalog` v6 and
  `protocol/provider-access-availability` v3; catalog README paragraph. Catalog check: 0 errors,
  3 warnings, identical to design `main` `1de95b5`; `--since origin/main` reports 11 entities
  changed, each version-bumped. `environment/aigateway-mesh` and `protocol/http-api` were in the
  expected set but needed no change (Kubernetes selectors; a statement that stays true).
- 2026-09-25: merged — screamingface-design PR #25, merge commit `3ba6a3d` (tree identical to
  `0e071dd`); recorded on `OME-1377`. Closed with the close comment. Left for a later catalog
  refresh: solution `completions` still says saved defaults are read before the cache lookup,
  which is stale since Stage C.

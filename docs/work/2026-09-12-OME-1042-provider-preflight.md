---
ticket: OME-1042
stack: screamingface
status: blocked
started: 2026-09-12
finished:
---

# OME-1042 — provider preflight

## Intent

Raise an actionable provider-access error before Recipe evaluation dispatches any
Candidate, without rejecting valid hosted or profileless access.

## Planned changes

- Client evaluation preflight and sync/async regression tests, after resolving the
  access-authority gap described in the specification and plan.
- Task mirror, specification, implementation plan, and this ledger.

## Test plan

- Missing and partially available providers: zero dispatches and ProviderConnectionError.
- Local BYOK, hosted profiles, and Gemini environment-key access: permitted.
- Discovery authentication and transport errors: preserve their original types.
- Full screamingface quality gates before an implementation commit.

## Acceptance

- Only authoritative absence of required access fails evaluation before dispatch.
- No inference request is made by preflight; doctor remains independent.

## Outcome

- Investigation at origin/main c1c92562 found no OME-1042 PR or existing preflight.
- No production or test files changed; no implementation gates run yet.
- Existing connection discovery is not an execution-access authority: it projects
  stored connection/profile rows and misses Gemini's supported environment-key path.
- Model details intentionally allow credential-free lookup (OME-1167).
- Awaiting owner direction on expanding into Gateway/Engine/Client units; see
  docs/plan/2026-09-12-OME-1042-provider-preflight.md.
- Commit: `docs: record provider preflight design` (Refs: OME-1042).
- Validation: documentation diff reviewed and `git diff --cached --check`; no runtime
  changes, so application tests are not applicable.
- Owner requested a draft PR for these findings and the proposed plan. The draft
  does not claim to implement or resolve OME-1042.

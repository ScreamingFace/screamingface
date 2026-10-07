---
id: OME-1446
linear_url: https://linear.app/openmined/issue/OME-1446/one-rate-limited-retry-blanks-a-runs-cost-and-token-counts
status: pick_immediately
type: bug
priority: high
labels: [bug, aigateway, agentic]
created: 2026-10-01
---

# One rate-limited retry blanks a run's cost and token counts

A failed OpenRouter attempt without usage makes a later successful retry's call cost and tokens
unknown. The accounting rule is correct; the missing capability is a truthful representation for a
provider-proven zero-charge rejection.

Spec: `docs/spec/2026-10-06-OME-1446-proven-zero-retry-accounting.md`.
Plan: `docs/plan/2026-10-06-OME-1446-proven-zero-retry-accounting.md`.
Ledger: `docs/work/2026-10-05-proven-zero-retry-accounting.md`.

- 2026-10-01: filed from paid-smoke evidence; blocked on whether OpenRouter bills the rejected try.
- 2026-10-06: planning corrected to use a dedicated proven-zero status, preserving one reported
  subtotal and avoiding an Engine change.
- 2026-10-06: owner authorized the narrow cost-only implementation backed by OpenRouter's current
  insurance and router-metadata contracts. Bare 429s and token counts remain unknown.
- 2026-10-06: implementation and full AIGateway gates completed in the dedicated worktree. The only
  remaining acceptance step is a separately authorized paid/live retry smoke; nothing was staged or
  committed.
- 2026-10-07: independent implementation review returned `NOT READY` after reproducing additional
  fail-open request, pipeline-cost, token, cost-detail and attempt-chain cases. Additive corrections,
  full gates and mutation-sensitive independent re-review are now green with verdict `READY`. The
  separately authorized live smoke remains outstanding. No live call, staging, commit, push or Linear
  mutation occurred.
- 2026-10-07: the verified implementation is captured by this branch commit. A fresh post-commit
  review follows from the immutable commit diff; the paid/live smoke remains separately authorized.

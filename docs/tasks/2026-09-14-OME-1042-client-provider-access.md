---
id: OME-1042
linear_url: https://linear.app/openmined/issue/OME-1042
status: In Review
type: bug
priority: medium
labels: [py-screamingface, autonomous, agentic]
created: 2026-08-31
closed:
---

# Raise ProviderConnectionError before evaluation starts when no provider is connected

Client unit of OME-1194. Consume Gateway #932 / OME-1195 `context.execution_access` via existing Engine passthrough; reject missing access before any Candidate dispatch. Preserve valid hosted/profileless access, typed discovery errors, and compatibility with older Gateways. See the 2026-09-14 Client spec, plan and work ledger. Gateway remains a deployment dependency; this branch starts independently from origin/main.

Semantic rebase (2026-09-16): rebased onto `0c0abfcf`, retaining all-model access checks, answer-seed validation and admission reuse. Explicit None fallback included; shared helper extraction deferred. 91 combined tests and full Client gates pass, coverage 95.23%. Ledger: `docs/work/2026-09-16-OME-1042-semantic-rebase.md`. PR remains in review.

2026-09-17: owner approved replay-CI follow-up; ledger docs/work/2026-09-17-OME-1042-replay-access.md. No Linear comments.

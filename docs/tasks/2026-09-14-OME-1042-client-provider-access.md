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

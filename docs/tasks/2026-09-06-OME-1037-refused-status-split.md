---
id: OME-1037
linear_url: https://linear.app/openmined/issue/OME-1037/refused-means-a-provider-failure-in-one-benchmark-and-correct-behavior
status: in_progress
type:
priority: medium
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-06
closed:
---

# "Refused" means a provider failure in one benchmark and correct behavior in another

Re-partition the case-status space: `CaseStatus` drops `refused`. A refusal the
benchmark can grade becomes an ordinary `scored` case carrying `refusal` text
(exactly one of `output`/`refusal` set); a refusal the benchmark cannot grade becomes
a `failed` case carrying a `provider_refusal` failure plus the grading failures.
`CandidateInvocationStatus` (`completed`/`refused`) is untouched — at the invocation
layer "refused" is unambiguous.

Full issue body: see linear_url. Work ledger:
`docs/work/2026-09-06-OME-1037-refused-status-split.md`.

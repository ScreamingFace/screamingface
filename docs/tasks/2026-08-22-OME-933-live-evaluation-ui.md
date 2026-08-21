---
id: OME-933
linear_url: https://linear.app/openmined/issue/OME-933/redesign-live-evaluation-progress
status: todo
type: improvement
priority: 2
labels: [py-screamingface, agentic, deferred]
created: 2026-08-21
closed:
---

# Redesign live Evaluation progress

Build the SFDS v2 notebook Candidate table from the existing Client Event callback plus OME-932
terminal Case snapshots.

The table uses Candidate, Status, Progress, Score, Cost, and Cache columns. Existing Events keep
`Running` rows visibly alive; OME-932 provides accurate completed/total bars and provisional
native scores. The Client does not infer Answering/Grading/current-Case phases, parse URL4, or
compute Benchmark scores. Final `CandidateResult` values remain authoritative.

Blocked by OME-932.

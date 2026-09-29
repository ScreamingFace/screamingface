---
id: OME-1406
linear_url: https://linear.app/openmined/issue/OME-1406/show-benchmark-native-running-scores-in-the-evaluation-table
status: In Review
type: feature
priority: 2
labels: [client-sf, agentic, autonomous]
created: 2026-09-29
closed:
---
# Show benchmark-native running scores in the evaluation table

Parent: OME-887. Engine producer: OME-932. PR: https://github.com/ScreamingFace/screamingface/pull/1096.

Tracks the Client code already implemented in that PR: validate cumulative snapshots, update independent numeric Score cells, prefer authoritative results, and suppress partial scores on terminal rows without a final result. No additional implementation or separate PR is required.

Validation: Client full gates and contract, terminal-state, invalid-snapshot and interleaved-candidate regressions passed. Ledger: docs/work/2026-09-29-live-score-review-completion.md. Linear is the status authority; awaiting review and merge.

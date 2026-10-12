---
id: OME-1583
linear_url: https://linear.app/openmined/issue/OME-1583/add-sfvote-and-sfmedian-with-the-benchmark-answer-rule
status: in_progress
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add sf.Vote and sf.Median with the benchmark answer rule

Mirror of OME-1583 (parent epic OME-1289). PR 6 of 16 in the E4a stack, branch
`OME-1583-e4a-vote-median` on `OME-1582-e4a-sdk-reducer-slot`.

Add the two named reducers. `sf.Vote(extract="benchmark")` uses the grader's own answer rule, resolved before any spend; a url4 rebuilds as the named reducer when it matches exactly, else as `sf.Reduce`.

Ledgers: `docs/work/2026-10-01-e4a-vote-median.md`, `docs/work/2026-10-02-e4a-gap-closure-unit5.md`.

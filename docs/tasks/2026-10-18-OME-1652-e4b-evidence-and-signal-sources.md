---
id: OME-1652
linear_url: https://linear.app/openmined/issue/OME-1652/add-evidence-completeness-and-declared-signal-sources-to-combine
status: in_progress
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-18
closed:
---

# Add evidence completeness and declared signal sources to combine

Mirror of OME-1652 (parent epic OME-1290, E4b). E4b parts 2 and 3 in one PR, stacked on part 1
(OME-1601). Branch `OME-1652-e4b-evidence-and-signal-sources`.

Scope: part 2 records the cut, the excluded members and the ranks in the combine evidence, and
refuses reduce/select pairs outside `REDUCE_SELECT_RULES`; part 3 adds the declared signal sources
`sf.Verbalized`, `sf.Logprob` and `sf.Entropy`, the injected `logprobs` member parameters, and the
`logprobs_unsupported` failure.

Design: `docs/spec/2026-10-15-e4b-evidence-completeness/`, `docs/spec/2026-10-15-e4b-signal-sources/`.
Ledgers: `docs/work/2026-10-15-e4b-evidence-completeness.md`, `docs/work/2026-10-15-e4b-signal-sources.md`.
Test approvals: `.claude/test-change-approvals/OME-1652.json`.

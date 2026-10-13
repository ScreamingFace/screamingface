---
id: OME-1589
linear_url: https://linear.app/openmined/issue/OME-1589/add-sfjudge-and-judge-weighted-votes
status: in_progress
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add sf.Judge and judge-weighted votes

Mirror of OME-1589 (parent epic OME-1289). PR 12 of 16 in the E4a stack, branch
`OME-1589-e4a-judge-pick-sdk` on `OME-1588-e4a-rank-concat-engine`.

`sf.Judge(model, returns="label" | "scores", rubric=…)` as a hashable value and block form, and `sf.Vote(weights=sf.signal("score:judge"), judge=sf.Judge(…))`. A judge on a quorum Fusion reads the panel through its own template form.

Ledgers: `docs/work/2026-10-01-e4a-judge-pick-sdk.md`, `docs/work/2026-10-02-e4a-gap-closure-unit8s.md`.

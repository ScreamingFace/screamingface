---
id: OME-1146
linear_url: https://linear.app/openmined/issue/OME-1146/rename-the-score-for-cost-chart-to-pareto-frontier-costscore-and-drop
status: in_review
type: task
priority: 2
labels: [BUG, scoreboard, agentic, autonomous]
created: 2026-09-08
closed:
---

# Rename the "Score for cost" chart to "Pareto Frontier (cost/score)"

Part 1 of OME-1146: the rename only. The heading and the scroll region's `aria-label` on
`portal/benchmark.html` take the name used everywhere else on the page.

**The ticket stays open.** Its second half — deleting the self-reported-costs disclaimer —
reverses `OME-770` D11 and contradicts recorded invariants in `scores/models/score.py` and
`scores/schemas.py`. The question is posted on the ticket and awaits the owner.

## Artifacts

- Spec: `docs/spec/2026-09-10-OME-1146-pareto-chart-title.md`
- Plan: `docs/plan/2026-09-10-OME-1146-pareto-chart-title.md`
- Ledger: `docs/work/2026-09-10-OME-1146-pareto-chart-title.md`

Related: `OME-923` (introduced the Pareto frontier naming), `OME-770` (D11, the disclaimer),
`OME-1143` (costs on this chart are currently wrong for cached runs).

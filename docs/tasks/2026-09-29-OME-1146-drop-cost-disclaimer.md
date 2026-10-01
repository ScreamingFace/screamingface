---
id: OME-1146
linear_url: https://linear.app/openmined/issue/OME-1146/rename-the-score-for-cost-chart-to-pareto-frontier-costscore-and-drop
status: done
type: task
priority: 2
labels: [bug, scoreboard, agentic, autonomous]
created: 2026-09-08
closed: 2026-09-30
---

# Drop the self-reported-costs disclaimer

Part 2 of OME-1146: the disclaimer removal, deliberately held back from part 1. Owner decided to
proceed without waiting for `OME-1382` (the cost-accuracy fix) to ship, accepting the chart will
be temporarily cost-inaccurate for `draco-3pass` with no specific caveat, until that lands.

## Artifacts

- Spec: `docs/spec/2026-09-29-OME-1146-drop-cost-disclaimer.md`
- Plan: `docs/plan/2026-09-29-OME-1146-drop-cost-disclaimer.md`
- Ledger: `docs/work/2026-09-29-OME-1146-drop-cost-disclaimer.md`
- Part 1 (rename only): `docs/{spec,plan,work}/2026-09-10-OME-1146-pareto-chart-title.md`

Related: `OME-1143` (cached runs submit $0.00 — still open), `OME-1382` (the fix — designed, not
shipped), `OME-1319` (broader verification-semantics question — separate, still open with Irina).
- 2026-09-30: part 2 merged via #1123 (`ea9f8d7c`); with part 1 (#892) the ticket is complete and closed in Linear.

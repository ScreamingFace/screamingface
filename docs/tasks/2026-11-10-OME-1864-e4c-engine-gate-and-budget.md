---
id: OME-1864
linear_url: https://linear.app/openmined/issue/OME-1864/run-only-the-branch-a-gate-takes-and-enforce-the-per-case-budget-in
status: in_progress
type: feature
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-11-10
closed:
---

# Run only the branch a Gate takes and enforce the per-Case budget in the Engine

Mirror of OME-1864 (parent epic OME-1291, E4c). Scope: gated url4 iterate (a model on the branch not taken is not called), the lazy E4b fallback, selectors, skip-Gate members, guards (`fail_closed`, `quorum_not_met`), the per-Case budget with `budget_refused`, one replay price (Q21b), and `OperationOutput.charges` (Q32). One PR for the three E4c leaves: OME-1864 (Engine),
OME-1865 (SDK), OME-1866 (aigateway). Branch `OME-1864-e4c-routers-cascades`.

Design: `docs/spec/2026-10-22-e4c-routers-cascades/`, plan `docs/plan/2026-10-22-e4c-routers-cascades.md`.
Ledger: `docs/work/2026-10-22-e4c-routers-cascades.md`.
Test approvals: `.claude/test-change-approvals/OME-1291.json`.

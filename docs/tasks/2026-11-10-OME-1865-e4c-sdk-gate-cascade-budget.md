---
id: OME-1865
linear_url: https://linear.app/openmined/issue/OME-1865/add-sfgate-routing-sfcascade-and-per-case-budgets-to-the-sdk
status: done
type: feature
priority: 2
labels: [client-sf, agentic, autonomous]
created: 2026-11-10
closed: 2026-11-16
---

# Add sf.Gate routing, sf.Cascade and per-Case budgets to the SDK

Mirror of OME-1865 (parent epic OME-1291, E4c). Scope: `sf.Gate` as the one branch construct, `sf.Cascade`, `sf.Keywords`, `sf.LabelModel`, skip-Gate members, guards, `sf.Estimate`, `sf.Budgeted`, the report (Gate decision, calls avoided, budget and overspend line from the Engine charges, Q32), notebook 20 and the README. Release the SDK before the Engine (OME-1233 rule). One PR for the three E4c leaves: OME-1864 (Engine),
OME-1865 (SDK), OME-1866 (aigateway). Branch `OME-1864-e4c-routers-cascades`.

Design: `docs/spec/2026-10-22-e4c-routers-cascades/`, plan `docs/plan/2026-10-22-e4c-routers-cascades.md`.
Ledger: `docs/work/2026-10-22-e4c-routers-cascades.md`.
Test approvals: `.claude/test-change-approvals/OME-1291.json`.

## Close

- 2026-11-16: PR #1733 (one PR for OME-1864/1865/1866) merged as `baedbd47a` on 2026-11-13. The epic OME-1291 stays open. Linear Done 2026-11-16 with a close-comment that names the PR and the merge commit; checked against `origin/main`.

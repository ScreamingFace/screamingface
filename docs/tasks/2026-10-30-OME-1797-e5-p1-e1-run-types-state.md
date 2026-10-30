---
id: OME-1797
linear_url: https://linear.app/openmined/issue/OME-1797/add-the-run-types-state-rule-and-the-database-writes-layering-rule-e5
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1785
created: 2026-10-30
closed:
---

# Add the Run types, state rule and the database-writes layering rule (E5 P1 · E1)

First PR of the E5 P1 Engine stack. It adds the layering rule that keeps every database write in
the App (the runner, the worker and shared leaves can't import the Run registry; only the
registry imports the database stack), the Run domain types, the R5 state function and the
monotonic UUIDv7 `run_` id. Nothing is wired.

Plan: `docs/plan/2026-10-30-e5-p1-first-class-run.md` (E1).
Ledger: `docs/work/2026-10-30-e5-p1-e1-run-types-state.md`.

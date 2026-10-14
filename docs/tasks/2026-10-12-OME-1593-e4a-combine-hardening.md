---
id: OME-1593
linear_url: https://linear.app/openmined/issue/OME-1593/freeze-the-combine-schemas-add-budgetv1-and-check-replays-before-spend
status: in_progress
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-12
closed:
---

# Freeze the combine schemas, add budget.v1 and check replays before spend

Mirror of OME-1593 (parent epic OME-1289). PR 16 of 16 in the E4a stack, branch
`OME-1593-e4a-combine-hardening` on `OME-1592-e4a-e2e-replay`.

Freeze the spec, evidence, Answer, trace and budget schemas (a change needs a v2), add `screamingface.budget.v1`, check the operator catalog before a raw url4 replay spends, and run the SDK-compiled quorum reducers in the Engine world.

Ledgers: `docs/work/2026-10-01-e4a-combine-hardening.md`, `docs/work/2026-10-02-e4a-gap-closure-unit12.md`.

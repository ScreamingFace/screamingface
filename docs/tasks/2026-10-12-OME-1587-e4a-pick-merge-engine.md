---
id: OME-1587
linear_url: https://linear.app/openmined/issue/OME-1587/add-the-pick-and-merge-field-operators
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add the pick and merge field operators

Mirror of OME-1587 (parent epic OME-1289). PR 10 of 16 in the E4a stack, branch
`OME-1587-e4a-pick-merge-engine` on `OME-1586-e4a-judge-pick-engine`.

Combine JSON answers field by field: pick the member with the best value of a field, or merge with one rule per field (majority, max, union, from one member, or a model writes it). A merge, projection or pick that finds no usable value abstains.

Ledgers: `docs/work/2026-10-01-e4a-pick-merge-engine.md`, `docs/work/2026-10-02-e4a-gap-closure-unit9e.md`.

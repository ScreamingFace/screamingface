---
id: OME-1581
linear_url: https://linear.app/openmined/issue/OME-1581/wire-combine-into-the-engine-and-score-abstained-cases
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-12
closed:
---

# Wire combine into the engine and score abstained cases

Mirror of OME-1581 (parent epic OME-1289). PR 4 of 16 in the E4a stack, branch
`OME-1581-e4a-engine-wiring` on `OME-1580-e4a-answer-operators`.

Serve the combine route in every benchmark world, carry the evidence on the operation output, serve `GET /v1/operators` so the SDK can check before it spends, and declare the GSM8K and AIME answer rules. An abstained Case scores 0.0 on every named score and keeps the grader's metrics and checks; an asset defect stays failed.

Ledgers: `docs/work/2026-10-01-e4a-engine-wiring-evidence.md`, `docs/work/2026-10-02-e4a-gap-closure-unit3.md`.

---
id: OME-1580
linear_url: https://linear.app/openmined/issue/OME-1580/add-the-answer-operators-for-deterministic-combine
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add the answer operators for deterministic combine

Mirror of OME-1580 (parent epic OME-1289). PR 3 of 16 in the E4a stack, branch
`OME-1580-e4a-answer-operators` on `OME-1579-e4a-combine-core`.

Add the v1 extract, normalize, reduce and select operators: `last_number`, `boxed`, `json_field`, `regex@1` on RE2 (linear time, size-capped), Inspect's own numeric rule vendored so a vote reads GSM8K and AIME answers the way the grader does, plurality, weighted mode, median and first holder. Each operator has a golden fixture.

Ledgers: `docs/work/2026-09-30-e4a-answer-operators.md`, `docs/work/2026-10-02-e4a-gap-closure-unit2.md`.

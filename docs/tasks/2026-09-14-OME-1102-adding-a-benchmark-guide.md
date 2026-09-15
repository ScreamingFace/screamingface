---
id: OME-1102
linear_url: https://linear.app/openmined/issue/OME-1102/write-the-adding-a-benchmark-guide-and-review-the-grade-case-hook-as-a
status: in_progress
type: task
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-03
closed:
---

# Write the adding-a-benchmark guide and review the grade_case hook as a public seam

Write `apps/screamingface-engine/docs/adding-a-benchmark.md` — the procedure a stranger
follows to add a benchmark (two-axis choice, case-row shape, `grade_case` per grading
mode, `failure_policy`, registry, assets, e2e onboarding) — and review the `grade_case`
signature against an external in-enclave judge shape, recording the result as a decision
in the doc. Last in the fold chain: written after draco (`OME-1100`), ifeval (`OME-1101`)
and MedXpertQA (`OME-1149`) are on the spine, so it describes a stable seam.

Parent: `OME-1024`. Ledger: `docs/work/2026-09-14-OME-1102-adding-a-benchmark-guide.md`.

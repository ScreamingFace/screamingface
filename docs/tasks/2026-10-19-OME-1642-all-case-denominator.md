---
id: OME-1642
linear_url: https://linear.app/openmined/issue/OME-1642/calculate-screamingface-scores-across-all-cases-not-just-successful
status: in_review
type: fix
priority: high
labels: [bug, screamingface-engine, agentic, autonomous]
parent:
created: 2026-10-16
closed:
---

# Calculate ScreamingFace scores across all cases, not just successful ones

Mean-score Benchmarks divide the sum of Case grades by the graded Cases only, so a failed Case
(a content-filter refusal, an error, an empty reply) leaves the denominator and raises the
score. On FrontierScience this lifts claude-opus-5.5 from 0.6287 to 0.7396 (24 content-filter
refusals). The fix implements the declared `withhold` failure policy (failed Case = 0, all
selected Cases in the denominator) for the mean-score Benchmarks, gives each switched Benchmark
a new revision, and leaves DRACO, refusal-measuring and whole-run-metric Benchmarks unchanged.

Spec: ../spec/2026-10-19-OME-1642-all-case-denominator.md
Plan: ../plan/2026-10-19-OME-1642-all-case-denominator.md
Ledger: ../work/2026-10-19-OME-1642-all-case-denominator.md

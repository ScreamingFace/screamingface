---
id: OME-1932
linear_url: https://linear.app/openmined/issue/OME-1932/park-each-case-of-a-benchmark-runs-report-on-disk-so-the-aggregates
status: in_review
type: improvement
priority: none
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-16
closed:
---

# Park each Case of a benchmark run's report on disk so the aggregate's memory stays flat in the Case count

Unit 2 of memory fix 3, after OME-1835 (unit 1). Each marked Case's wire JSON is parked in the
run's Case-result store, and the builder keeps only its scoring projection. One finalize runs on
the builder. The hosted routes write the result body from the parked text, with the final
grading accounting from a frozen view. The bytes, the scores and the SDK contract do not change.
Peak per Case: 32.0 → 5.2 KiB (5-member Fusion), 11.6 → 6.2 KiB (1 model), the same at N=500 and
N=2,000.

Related: OME-1835, OME-1885, OME-1887.

Spec: `docs/spec/2026-11-16-streamed-candidate-result.md`. Plan: `docs/plan/2026-11-16-streamed-candidate-result.md`. Ledger: `docs/work/2026-11-16-parked-case-results.md`.

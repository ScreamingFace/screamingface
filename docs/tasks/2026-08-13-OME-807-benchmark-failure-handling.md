---
id: OME-807
linear_url: https://linear.app/openmined/issue/OME-807/implement-originals-faithful-benchmark-failure-handling
status: In Progress
type: Feature
priority: P1
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-13
---

# Implement originals-faithful benchmark failure handling

Replace the fail-closed Candidate finalization introduced by OME-802 with one shared policy that
grades model-authored responses and refusals normally, excludes only ungradeable infrastructure
failures, publishes factual top-level coverage, and still aborts on protocol corruption.

Spec: `docs/spec/2026-08-13-OME-807-benchmark-failure-handling.md`
Plan: `docs/plan/2026-08-13-OME-807-benchmark-failure-handling.md`
Ledger: `docs/work/2026-08-13-OME-807-benchmark-failure-handling.md`

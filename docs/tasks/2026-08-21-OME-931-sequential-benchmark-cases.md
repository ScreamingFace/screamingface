---
id: OME-931
linear_url: https://linear.app/openmined/issue/OME-931/evaluate-benchmark-cases-sequentially
status: in_progress
type: improvement
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-21
closed:
---

# Evaluate benchmark cases sequentially

Run the shared Engine benchmark protocol's outer Case iteration with URL4
`iteration.concurrency=1`. One complete Case evaluation therefore finishes or fails before the
next Case begins, while nested work inside a Case and separate benchmark runs retain their own
concurrency.

Canonical artifacts:

- Spec: `docs/spec/2026-08-21-OME-931-sequential-benchmark-cases.md`
- Plan: `docs/plan/2026-08-21-OME-931-sequential-benchmark-cases.md`
- Ledger: `docs/work/2026-08-21-OME-931-sequential-benchmark-cases.md`

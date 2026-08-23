---
id: OME-950
linear_url: https://linear.app/openmined/issue/OME-950/report-relative-url4-routes-in-span-names
status: in_progress
type: improvement
priority: 2
labels: [url4-python-sdk, agentic, autonomous]
created: 2026-08-23
closed:
---

# Report relative URL4 routes in span names

Expose a relative URL4 node's static path template through the existing observation detail and
span name. This lets a consumer recognize a terminal operation such as
`/benchmarks/case-execution` from ordinary spans without adding a semantic event channel.

Canonical artifacts:

- Spec: `docs/spec/2026-08-23-OME-950-relative-route-span-name.md`
- Plan: `docs/plan/2026-08-23-OME-950-relative-route-span-name.md`
- Ledger: `docs/work/2026-08-23-OME-950-relative-route-span-name.md`

---
id: OME-712
linear_url: https://linear.app/openmined/issue/OME-712/run-draco-end-to-end-as-a-url4-expression-on-the-runner-path
status: pick_immediately
type:
priority: P2
labels: [url4-cloud, autonomous, agentic]
created: 2026-07-31
closed:
---

# Run DRACO end to end as a url4 expression on the Runner path

Run the real DRACO protocol as ordinary URL4: benchmark artifacts are addressable Engine
resources, Candidate and judge invocations remain observable URL4 calls, and aggregation is
deterministic arithmetic. A failed or empty evaluation must never look like a valid score.

This mirror reflects Linear as read on 2026-08-04. The issue spans `packages/url4`,
`apps/aigateway`, and `apps/url4-cloud`, while its current landing label is `url4-cloud`.
Per owner direction, this stack cleanup reuses OME-712 and proposes any Linear corrections
for owner approval rather than creating or mutating issues automatically.

Layer-specific artifacts:

- `docs/spec/2026-08-04-OME-712-url4-runtime-foundations.md`
- `docs/plan/2026-08-04-OME-712-url4-runtime-foundations.md`
- `docs/work/2026-08-04-OME-712-url4-runtime-foundations.md`


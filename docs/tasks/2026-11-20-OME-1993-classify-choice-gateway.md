---
id: OME-1993
linear_url: https://linear.app/openmined/issue/OME-1993/serve-the-gateway-side-of-routers-structured-choice-classification
status: Done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1306
created: 2026-11-20
closed: 2026-11-20
---

# Serve the Gateway side of Routers: structured-choice classification, upstream attempt counts and seal provenance

Router Recipe extension Unit 5.1, the Gateway side: contract C7 and the Gateway reader of C9.

A configured endpoint can declare a `systemone-choice-v1` classifier target.
`POST /v1/classifications` sends one native SystemOne `choice` question for it and returns the label
probabilities as `classification-scores-v1`, unchanged and in returned order. Targets can declare
`classifier-limits-v1` limits, and catalog rows gain `input_contracts` and `limits`. Every
non-streaming chat and classification answer carries `X-AIGW-Upstream-Attempts`. A seal accepts the
run's Router manifest, and the provenance read returns it in a strict shape. The scalar
classification path stays byte-identical.

Fake upstreams only. Two owner-approved prior test changes, pinned by
`.claude/test-change-approvals/OME-1993.json`. No hosted readiness claim.

Spec: `docs/spec/2026-11-16-router-recipe-extension/` (C7, C9).
Plan: `docs/plan/2026-11-16-router-recipe-extension.md` §6.
Ledger: `docs/work/2026-11-19-classify-choice-gateway.md`.
Branch: `OME-1993-classify-choice-gateway`.

Merged [PR #1988](https://github.com/ScreamingFace/screamingface/pull/1988) as `9ef7c150c`.
Linear is Done.

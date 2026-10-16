---
id: OME-1499
linear_url: https://linear.app/openmined/issue/OME-1499/enable-local-models-in-fusion-and-benchmark-runs
status: in_progress
type: feature
priority: high
labels: []
created: 2026-10-14
closed:
---

# Enable local models in Fusion and benchmark runs

This mirror reflects the current Linear issue exactly: OME-1499 presently has no labels. The work is
cross-unit; any later landing/actor/who-acts normalization must update Linear first rather than invent
labels in this mirror.

Expose no-auth numeric-loopback OpenAI-compatible models through AIGateway, project them into the
local Engine execution world, and prove real Fusion member/synthesizer benchmark execution. The
implementation includes cold-start refresh, vLLM compatibility, bounded response validation,
byte-safe route identity projection, and a real process E2E. Spec:
`../spec/2026-10-16-OME-1499-local-model-fusion.md`. Plan:
`../plan/2026-10-16-OME-1499-local-model-fusion.md`.

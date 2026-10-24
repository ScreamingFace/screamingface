---
id: OME-1537
linear_url: https://linear.app/openmined/issue/OME-1537/expose-each-models-input-modalities-on-v1models
status: in_progress
type: feature
priority: 2
labels: [aigateway, agentic, autonomous]
created: 2026-10-09
closed:
---

# OME-1537 — Expose each model's input modalities on /v1/models

Leaf of epic `OME-1529` (image inputs in url4). Every `/v1/models` row carries
`input_modalities` (`text`/`image`/`pdf`); unknown is `["text"]`, never vision.

Spec: ../spec/2026-10-16-input-modalities.md
Plan: ../plan/2026-10-16-input-modalities.md
Ledger: ../work/2026-10-16-input-modalities.md

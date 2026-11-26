---
id: OME-2045
linear_url: https://linear.app/openmined/issue/OME-2045/pin-the-isolated-unit-8a-distilbert-reference-contract
status: In Review
type: task
priority: high
labels: [repo-dev-processes, autonomous]
parent: OME-1306
created: 2026-11-26
closed:
---

# Pin the isolated Unit 8A DistilBERT reference contract

Pin the fixed-label reference classifier contract before any serving implementation or model
provisioning. The amendment selects an immutable Apache-2.0 DistilBERT checkpoint, ordered labels and
score semantics, the exact native request/refusal boundary, and an isolated offline artifact contract.

The change is documentation only. Downloaded weights and tokenizer artifacts remain outside Git,
packages, images and release archives. Router integration and real/live qualification remain separate.

Spec: `docs/spec/2026-11-16-router-recipe-extension/`.
Plan: `docs/plan/2026-11-16-router-recipe-extension.md` section 12.
Ledger: `docs/work/2026-11-26-unit-8a-spec-pins.md`.
Branch: `OME-2045-unit-8a-spec-pins`.

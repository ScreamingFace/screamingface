---
id: OME-625
linear_url: https://linear.app/openmined/issue/OME-625
status: In Progress
type: Feature
priority: P2
labels: [url4-cloud, autonomous, agentic]
created: 2026-07-26
closed:
---

# Expose only executable models from the Engine catalog

Project the existing caller-visible AI Gateway catalog onto the model routes declared by this
Engine's `url4.toml`. The App and Runner consume one shared declared-world parser, so discovery
cannot advertise a route whose complete execution configuration is invalid. Apply the same set to
model-parameter lookup and reject undeclared models without contacting AI Gateway.

Spec: `docs/spec/2026-07-26-url4-cloud-model-catalog-spec.md`
Plan: `docs/plan/2026-07-26-url4-cloud-model-catalog.md`
Ledger: `docs/work/2026-08-05-OME-625-executable-model-catalog.md`

---
id: OME-883
linear_url: https://linear.app/openmined/issue/OME-883/render-hosted-engine-provider-access-without-byok-controls-in
status: In Review
type: improvement
priority: high
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-18
closed:
---

# Render hosted Engine provider access without BYOK controls in `sf.connect()`

Treat loopback Engine origins as local BYOK environments and other Engine origins as hosted
environments in the notebook connection panel. Hosted provider rows retain the status reported
by the Engine only for catalogue membership and expose no credential mutation controls. Every
advertised hosted provider reads “Connected” and “Available via ScreamingFace”; caller-scoped
BYOK status is ignored because it does not describe operator-managed credentials. The Engine and
AI Gateway wire contracts are unchanged.

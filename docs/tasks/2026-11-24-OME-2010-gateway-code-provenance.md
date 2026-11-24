---
id: OME-2010
linear_url: https://linear.app/openmined/issue/OME-2010/lift-only-the-gateways-declared-error-codes-from-a-gateway-error-body
status: in_progress
type: fix
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1306
created: 2026-11-24
closed:
---

# Lift only the Gateway's declared error codes from a Gateway error body

The Engine lifts a Gateway error body's `detail.code` only when the Gateway declares that code.
Any other code takes `aigateway_http_<status>`. A body from a proxy, a provider or an unreviewed
Gateway build can then no longer put a key, an origin or a private ID into the model-call log
line, `observation.failed()` or the benchmark report.

`world/gateway_codes.py` holds `GATEWAY_CODES`, the 97 codes the Gateway declares less the codes
the Engine reserves, and `world/connector.py::_upstream_code` lifts only those. A parity test pins
the set to the Gateway fixture exactly, with the three reserved Gateway codes pinned. Six prior
tests change their code strings only, at the owner-approved blobs pinned in
`.claude/test-change-approvals/OME-2010.json`.

This releases the merge gate of the BYOM routing pilot (PR #2016). No hosted readiness claim.
The sibling Gateway leaf, OME-2011, lands in the same PR.

Spec: `docs/spec/2026-11-23-gateway-code-provenance.md`.
Plan: `docs/plan/2026-11-23-gateway-code-provenance.md`.
Ledger: `docs/work/2026-11-23-gateway-code-provenance.md`.
Branch: `OME-2010-gateway-code-provenance`.

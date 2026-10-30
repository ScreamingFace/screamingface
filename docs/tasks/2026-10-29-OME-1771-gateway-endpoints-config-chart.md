---
id: OME-1771
linear_url: https://linear.app/openmined/issue/OME-1771/deliver-the-configured-endpoints-file-to-the-gateway-through-its-chart
status: backlog
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1306
created: 2026-10-29
---

# Deliver the configured endpoints file to the Gateway through its chart

Gateway deployment slice of hosted BYOM Unit 2. The Gateway already reads a configured endpoints
file at startup from `AIGW_REMOTE_ENDPOINTS_CONFIG`; its chart cannot deliver one yet. The Engine
slice is the sibling OME-1770; both land in one PR.

- Opt-in: with the feature disabled the chart renders exactly as today.
- Delivery: a privately supplied endpoints config from an existing Secret or ConfigMap reference,
  mounted read-only, its path passed in `AIGW_REMOTE_ENDPOINTS_CONFIG`, and a content checksum
  annotation taken from a supplied content revision, not from the resource name.
- No keys in the config, chart values or Git; keys stay in the Gateway credential store through
  the existing admin attach.
- Gateway code changes only where the integration boundary needs them.

Acceptance: Helm render with disabled, enabled and malformed values shows mount, env and checksum
parity; Gateway gates are green if Gateway code changes.

Ledger: `docs/work/2026-10-29-hosted-byom-unit2.md` (shared with OME-1770).

---
id: OME-1712
linear_url: https://linear.app/openmined/issue/OME-1712/serve-configured-remote-chat-endpoints-as-gateway-providers
status: in_progress
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1306
created: 2026-10-22
---

# Serve configured remote chat endpoints as gateway providers

First gateway slice of hosted BYOM: a compatibility proof on isolated storage, not the hosted
rollout.

- `AIGW_REMOTE_ENDPOINTS_CONFIG` lists approved OpenAI-compatible endpoints read at startup; each
  becomes its own provider instance with a stable ID, origin, chat targets and credential
  namespace. An invalid config fails as a whole; no config keeps the bundled providers unchanged.
- Keys attach, replace and delete through the existing admin Connection API. Readiness sends the
  request an ordinary chat sends and holds the answer to the dispatch decoder. A key is bound to
  its endpoint origin inside the encrypted blob.
- Explicit account grants gate every upstream path.
- Fake upstream HTTP proves two endpoints and two accounts stay isolated, with concurrency and a
  failed replacement.

Next slice: grant-filtered catalog and admission, cache projection, guarded transport, pooled
client, streaming, upstream 401 fencing, Engine config, classification, UI and Helm.

Ledger: `docs/work/2026-10-21-hosted-byom-unit0.md`.

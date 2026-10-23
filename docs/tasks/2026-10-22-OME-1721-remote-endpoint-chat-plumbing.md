---
id: OME-1721
linear_url: https://linear.app/openmined/issue/OME-1721/extend-configured-remote-endpoints-with-approved-origins-granted
status: in_progress
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1306
created: 2026-10-22
---

# Extend configured remote endpoints with approved origins, granted catalogs, a shared chat cache and a reused client

Second gateway slice of hosted BYOM, on top of OME-1712: the common chat plumbing for configured
endpoints, not the hosted rollout.

- Origins: HTTP and HTTPS with DNS names (single-label service names included), canonical IPv4 or
  bracketed IPv6, and ports 1 to 65535. Unspecified addresses, IPv4-mapped IPv6 in any spelling
  and IPv6 zones are refused. The default port is normalized away.
- Catalog: listings, availability, the model contract, admission and OAuth start show an endpoint
  only to the accounts its grant names; others get the route's unknown-provider answer. The two
  listings are `private, no-store` with `Vary: Authorization`. Availability lists only registered
  providers the caller may see, and reads no other provider's stored pair.
- Shared cache: a text chat is keyed from the request body alone, `max_tokens` included, and is
  shared by every account. The endpoint takes part only while it is enabled and the requested
  alias is declared; turning either off serves no row and keeps every row.
- Client: one reused HTTP client per endpoint with a bounded pool and no cookie store, closed at
  shutdown even when another endpoint's close fails; a chat after shutdown gets a safe 502.

Next slice: hosted chat integration and the Engine bridge.

Ledger: `docs/work/2026-10-22-hosted-byom-unit1.md`.

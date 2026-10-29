---
id: OME-1779
linear_url: https://linear.app/openmined/issue/OME-1779/speak-of-connections-not-provider-profiles-in-the-sdks-messages
status: in_review
type: task
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
---

# Speak of Connections, not provider profiles, in the SDK's messages

OME-1138 close-out leaf L8 (spec `docs/spec/2026-10-29-ome-1138-closeout.md` §4.8). The Client
SDK's messages stop pointing users at a "selected provider profile":

- The `provider_not_connected` preflight hint says to connect the provider with `sf.connect()`, or
  to ask the operator of a hosted Engine to connect it in AI Gateway.
- A relayed `model_not_found` reads `Model '<id>' is not in AI Gateway's catalogue`.
- The README and the `Client.models.get` / `AsyncClient.models.get` docstrings call `ModelDetails`
  Connection-specific.

The unit also removes the stale `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` comment and its test
assertion, and the e2e capture proxy stops forwarding `X-Profile`. The error codes and the R3
decoder are unchanged.

- 2026-10-29: filed, implemented, PR opened.

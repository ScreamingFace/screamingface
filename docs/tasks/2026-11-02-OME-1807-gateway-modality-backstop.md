---
id: OME-1807
linear_url: https://linear.app/openmined/issue/OME-1807/openrouter-bills-a-pdf-sent-to-an-image-only-model-then-the-gateway
status: done
type: bug
priority: none
labels: [bug, aigateway]
created: 2026-11-02
closed: 2026-11-04
---

# OpenRouter bills a PDF sent to an image-only model, then the gateway reports a retryable provider_error

The gateway's chat admission now refuses an `image_url` or `file` part with a 422
`unsupported_content_part` (permanent) when the routed model's published modalities lack `image` or
`pdf`. The refusal happens before the cache, credentials, or any upstream call, for every provider
including OpenRouter. Owner decisions (2026-11-02): refuse only on published evidence, so a model with
unknown modalities passes as before; chat reads a cached catalog snapshot and never fetches one. Found
by the OME-1551 end-to-end run.

Ledger: `docs/work/2026-11-02-gateway-modality-backstop.md`.

---
id: OME-1770
linear_url: https://linear.app/openmined/issue/OME-1770/run-configured-endpoint-chat-models-through-the-engine-with-private
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1306
created: 2026-10-29
---

# Run configured endpoint chat models through the Engine with private routes and one shared world config

Engine slice of hosted BYOM Unit 2, on top of the merged Gateway slices OME-1712 and OME-1721.
The Gateway chart delivery is the sibling OME-1771; both land in one PR.

- Routes: explicit `[[aigateway.models]]` entries `<endpoint-id>/<model-alias>` with
  `web_search=false` in the existing world config. No automatic admission and no endpoint URLs or
  keys in Engine or worker metadata.
- World config: one privately supplied full world config for the App and the runner pool through
  the Engine chart, with the same source, a read-only mount, `URL4_RUNNER_CONFIG` and a content
  checksum annotation on both pod templates.
- Discovery and SDK preflight: truthful per account. A grant without a key stays `missing`; an
  ungranted account gets the omitted or unknown answer.
- Publication: `public_schema` metadata keeps private routes out of the shared OpenAPI, never
  inferred from a provider ID prefix; inventories, metrics and logs keep the same boundary.
- Execution: cold and warm runs need no prior list call; caller identity picks the Connection; no
  endpoint key in queue or worker payloads and no fallback to another account.
- Usage: a missing count shown as 0 is not a measured zero.

Acceptance: deterministic checks with substitutes and Engine gates; Helm render with disabled,
enabled and malformed config. **Pending:** one mixed Fusion through a real queue and workers,
which needs an existing Linux environment with NATS/JetStream, not available on 2026-10-29. Its
absence does not block development; until it passes, hosted readiness is not claimed and the
issue stays open.

Ledger: `docs/work/2026-10-29-hosted-byom-unit2.md`.

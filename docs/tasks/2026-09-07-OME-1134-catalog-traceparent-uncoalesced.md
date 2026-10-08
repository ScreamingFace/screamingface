---
id: OME-1134
linear_url: https://linear.app/openmined/issue/OME-1134/propagate-the-callers-traceparent-on-the-two-uncoalesced-catalog-calls
status: done
type: null
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-07
closed: 2026-10-01
---

# Propagate the caller's traceparent on the two uncoalesced catalog calls

Child of `OME-1129`, follow-up to `OME-1119` (raised in PR #849 review). `fetch_model_parameters`
and `admit_model` are one-to-one with an inbound request, so they now forward its validated
`traceparent` to aigateway. `fetch` stays traceless because `CachedCatalog` coalesces it across
callers. The trace is threaded as an explicit argument from the REST edge, never put on
`Credential`, whose derived key is the catalog cache key.

Ledger: `docs/work/2026-10-01-OME-1134-catalog-traceparent-uncoalesced.md`.

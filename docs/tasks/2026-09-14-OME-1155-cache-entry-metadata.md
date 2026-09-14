---
id: OME-1155
linear_url: https://linear.app/openmined/issue/OME-1155/cache-gateway-metadata-end-to-end-for-openrouter
status: in_progress
type: feature
priority: 3
labels: [aigateway, agentic]
created: 2026-09-14
closed:
---

# Cache gateway metadata end to end for OpenRouter

Cache the response along with cost, latency and any metadata the gateway returns, using a
standardized schema. A cached response must return complete metadata to the client in the same
format the gateway reports for a live call, so the engine is agnostic to whether the data came
from a provider or the cache. The client can then report both cost including cache behaviour and
full cost without accounting for cache hits.

Delivered as a nullable `metadata_json` column beside every cached row (migration 0011), read back
on a hit through `_aigw`, and totalled into two run-level saved-cost figures that are never
combined — provider-authored money and archive-paired money are different claims.

This mirror was created on 2026-09-14, during the review of PR #930: the work had been carried out
against no tracked work item, and the PR carried no `OME-N`. The issue itself pre-dates the work
and describes it exactly, so the work was attached to it rather than a new issue being filed.

Sub-issue: **OME-1156** — Design USD cost reporting for token-based providers (Triage, not started).

Spec: `docs/spec/2026-09-13-cache-entry-metadata-prd.md` ·
`docs/spec/2026-09-13-cache-entry-metadata-erd.md`
(both reconstructed 2026-09-14 from the implementation — see their provenance notes)
Ledger: `docs/work/2026-09-14-OME-1155-review-findings.md`
PR: https://github.com/ScreamingFace/screamingface/pull/930

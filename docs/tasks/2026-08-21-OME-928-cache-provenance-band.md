---
id: OME-928
linear_url: https://linear.app/openmined/issue/OME-928/show-live-cache-provenance-as-a-diagnostic-band-in-the-evaluation
status: in_progress
type: improvement
priority: 3
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-21
closed:
---

# Show live cache provenance as a diagnostic band in the evaluation panel

While a run is in flight, render cache provenance as one full-width band under a three-column stat
row: hit rate, hit/miss counts, and — only when bypasses occurred — the bypass total with the
Engine's per-reason breakdown, verbatim.

Motivated by Irina's request for a cache-hit percentage after the cost box, and by her own caveat
that she wasn't sure it was the right shape. A rate alone cannot separate a cold cache from one that
was never consulted, which is the case `OME-907` is investigating.

Client-only: the Engine already publishes hits, misses, bypasses and `cache.bypass.<reason>` on one
`ai.url4.log`; the Client read the three totals and discarded the breakdown.

Not filed against `OME-692` — that issue is Blocked on five dependencies and scopes cache write,
key, age and saved-cost totals, none of which this needs.

Spec: `docs/spec/2026-08-21-OME-928-cache-provenance-band.md`
Ledger: `docs/work/2026-08-21-OME-928-cache-provenance-band.md`

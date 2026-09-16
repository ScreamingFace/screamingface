---
id: OME-1114
linear_url: https://linear.app/openmined/issue/OME-1114/benchmark-listing-shows-our-boards-and-imported-boards-as-two-groups
status: done
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-04
closed: 2026-09-16
---

# Benchmark listing shows our boards and imported boards as two groups

SDK-side presentation of the `origin` field OME-1112 put on `GET /v1/benchmarks`:
`sf.benchmarks.list()` renders one tab per origin — "ScreamingFace" and
"inspect_evals" — each tab linking to its source collection
(leaderboard.dev.screamingface.ai / ukgovernmentbeis.github.io/inspect_evals).
Link map is SDK-side; an unmapped future origin auto-gets its own tab with no
link; decode accepts any non-blank origin string. Blocks OME-1202 (showcase
notebook).

Ledger: `docs/work/2026-09-16-OME-1114-benchmark-origin-tabs.md`

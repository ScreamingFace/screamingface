---
id: OME-1849
linear_url: https://linear.app/openmined/issue/OME-1849/refresh-the-request-architecture-diagram-and-reskin-the-docs-diagrams
status: In Progress
type: task
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1313
created: 2026-11-06
closed:
---

# Refresh the request-architecture diagram and reskin the docs diagrams

Remake the SF Client docs diagrams in one clean, un-branded style, stacked on OME-1842.

- New local request-architecture diagram (you → Client → engine → gateway → provider; cache
  accumulates and pulls from the global cache; verifiable submission → public leaderboard); wired
  into the SF Client landing.
- Two focused cuts: community-cache pull (community-cache guide) and verifiable submission
  (Leaderboard concept page).
- Two map-reduce guide diagrams (map→enrich→narrow→reduce spine; one-signal-two-ways), replacing
  the inline SVGs.
- Reskin the six sf-client-0-1-11-* diagrams to the same minimal style; redesign the pinned-cache
  state diagram.

Branch: `docs-request-architecture-diagram`, stacked on
`OME-1842-docs-mapreduce-community-cache-guides`.
Ledger: `docs/work/2026-11-06-docs-request-architecture-diagram.md`.

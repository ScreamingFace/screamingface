---
id: OME-1585
linear_url: https://linear.app/openmined/issue/OME-1585/add-constant-and-signal-weighted-votes
status: in_progress
type: feature
priority: 3
labels: [client-sf, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add constant and signal-weighted votes

Mirror of OME-1585 (parent epic OME-1289). PR 8 of 16 in the E4a stack, branch
`OME-1585-e4a-weighted-vote` on `OME-1584-e4a-samples`.

`sf.Vote(weights=[…])` and `weights=sf.signal("cost_usd")`. The SDK names each member's model calls as combine `sources`, so the Engine finds the right cost, and a replay from the cache gives the same weights.

Ledgers: `docs/work/2026-10-01-e4a-weighted-vote.md`, `docs/work/2026-10-02-e4a-gap-closure-unit7.md`.

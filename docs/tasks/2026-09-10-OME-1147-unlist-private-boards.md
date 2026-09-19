---
id: OME-1147
linear_url: https://linear.app/openmined/issue/OME-1147/unlist-the-healthbench-worst-30percent-challenge-from-the-portal-index
status: in_review
type: task
priority: 2
labels: [BUG, scoreboard, agentic, autonomous]
created: 2026-09-08
closed:
---

# Unlist the HealthBench Worst-30% challenge from the portal index

Filter private boards out of the portal index so the Fusion Monsters entry challenge stops
appearing as an empty card. `sf.leaderboards` keeps listing every benchmark so participants can
submit, and rankings stay private.

Web-only. No API, schema, migration or seed change — `BenchmarkSchema` already exposes
`visibility`.

Visibility stands in for provenance here; the owner's rule is "established versus ours", which
`OME-1112` will make expressible.

## Artifacts

- Spec: `docs/spec/2026-09-10-OME-1147-unlist-private-boards.md`
- Plan: `docs/plan/2026-09-10-OME-1147-unlist-private-boards.md`
- Ledger: `docs/work/2026-09-10-OME-1147-unlist-private-boards.md`

Related: `OME-894` (private boards), `OME-1112` (benchmark provenance), `OME-798` (portal JS tests
are named in the gate list, never globbed).

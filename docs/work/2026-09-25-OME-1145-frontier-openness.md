---
ticket: OME-1145
stack: scoreboard
status: planned
started: 2026-09-25
finished:
---

# OME-1145 — compute the open share over the cost/score Pareto frontier

## Intent

The "N% open" card on `draco-3pass` reads 0% for three reasons, recorded in
`docs/work/2026-09-10-OME-1145-openness-metric-review.md`. Model identities were discarded
(fixed: `OME-1180`/`OME-1181`). The statistic mixes benchmark revisions (live: 10 rows counted, 7
ranked). And it counts all rows rather than the frontier, which the owner decided on 2026-09-10
(D-L, D-N) to change. This unit migrates `GET /v1/leaderboard/{id}/frontier` to the frontier
basis. Spec: `docs/spec/2026-09-25-OME-1145-frontier-openness.md`.

## Planned changes

Pending the spec's decisions. Expected:

- `scores/frontier.py`: replaced by a frontier-basis computation
- `scores/schemas.py`: `FrontierResult` / `FrontierPoint` / `FrontierResponse`
- `scores/store.py`: a bounded `id, models` read for frontier ids
- `routes/leaderboard.py`: `get_frontier` reuses the ranked route's inputs and `pinned` gate
- `portal/benchmark.js`: `renderFrontier`
- tests: new files, plus the approved prior-test changes listed in spec §7

## Test plan

In the spec, §6.

## Acceptance

- the percentage counts only full-board Pareto frontier entries at the registered revision
- an entry is open only when every declared model is open (D1); unknown closes it (D4)
- rows with no `models` are excluded and counted; unrecognised models are counted
- a board with no registered revision reports no share, matching the ranked route's D12 gate
- full scoreboard gates green, including the portal Node suite

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

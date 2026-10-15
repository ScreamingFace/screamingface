---
ticket: OME-1596
stack: scoreboard
status: planned
started: 2026-10-13
finished:
---

# OME-1596 — author and paper metadata, and a Reproduce button, on the leaderboard

## Intent

Scoreboard half of the E14 follow-up agreed with Irina (2026-10-14/15): submitters can attach
`authors_metadata` and `paper_metadata` (open objects with known keys, bounded, matched to `authors`,
masked in public JSON, editable with the edit log); a public lookup from a pinned cache id to its
published score lets the SDK's `evaluate(pinned_cache=…)` (`OME-1613`) replay and judge; each fully
captured public row gets a Reproduce button behind a switch; the "Reproduced N times" line goes. Spec:
`docs/spec/2026-10-13-OME-1596-reproducible-row-mark.md` (owner-approved piece by piece, 2026-10-15).

The 2026-10-13 version of this unit (a reproducible / reproduced row mark) was dropped before any code.

## Planned changes

Pending the plan (`docs/plan/`). Expected areas: `scores/models/score.py`,
`scores/models/score_metadata_event.py`, migration `0021`, `scores/schemas.py`, `scores/store.py`,
`routes/scores.py`, `routes/leaderboard.py`, settings, `portal/benchmark.js`, `portal/spec.js`, tests.

## Test plan

Spec §7.

## Acceptance

Spec §7 and the Linear issue's acceptance list.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

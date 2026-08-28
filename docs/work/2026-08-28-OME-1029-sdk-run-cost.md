---
ticket: OME-1029
stack: screamingface
status: in_progress
started: 2026-08-28
finished:
---

# OME-1029 — Send run_cost_usd on leaderboard submissions from the SDK

## Intent

Scoreboard accepts `run_cost_usd`, the Engine produces a run total, and the SDK already holds it on
`CandidateResult.usage.cost_usd`. The submission payload just does not include it, so the column is
null on every row of every board.

This is the last link in the run-cost chain. It unblocks `OME-822` (make cost required) and part B
of `OME-923` (Pareto frontier marks), which cannot mark anything while no row carries a cost.

## Why now

The priorities doc lists cost frontier marking and Pareto determination as Milestone 1 **Musts** for
the leaderboard. Both need cost data. The live board returns `entries=0, with a cost=0`, and this is
the only reason.

## Facts re-verified before starting

Full table in the spec (§1), checked against `origin/main` at `dd51ea81`. The one that shapes the
implementation: the payload is handed to `json=`, which serialises with `json.dumps` and raises on a
`Decimal`. The value cannot be passed through unchanged, and `float` would corrupt money.

## Planned changes

Per the plan: three cost states → payload otherwise untouched → both submit paths → round-trip
against Scoreboard's schema → close-out.

## Test plan

The absent/zero distinction is pinned first and separately. A null read as zero would put an
unpriced run at the cheapest end of the very frontier `OME-923` is about to build.

## Acceptance

See spec §5.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">

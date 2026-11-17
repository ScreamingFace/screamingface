---
ticket: OME-1883
stack: repo
status: in_progress
started: 2026-11-04
finished:
---

# e5-p2-detached-run-spec — E5 P2 spec and plan: a detached Run

## Intent

The spec and plan for E5 P2 (`OME-1837`, under `OME-1294`; `OME-1611`, `OME-1617`):
`sf.evaluate(..., detach=True)` returns a Run at once, the Engine owns the Run until it ends, and
the user reattaches by `run_id` from any notebook or machine. It builds on the E5 P1 Run record
(`docs/spec/2026-10-27-e5-p1-first-class-run.md`). Docs only.

## Planned changes

- `docs/spec/2026-11-04-e5-p2-detached-run.md` (new)
- `docs/plan/2026-11-04-e5-p2-detached-run.md` (new)
- `docs/tasks/` mirrors for `OME-1837` (P2 — detach), `OME-1838` (P5 — run comparison) and this
  unit's leaf, `OME-1883`, filed under `OME-1837`.

## Design decisions (owner: Tauquir)

The decisions are the spec's §3, summarised in its §10.

## Test plan

- None: docs only. The spec's §6 lists the tests the code PRs write first.

## Acceptance

- The owner approves the spec, then the plan.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `docs/spec/2026-11-04-e5-p2-detached-run.md`,
  `docs/plan/2026-11-04-e5-p2-detached-run.md`, this ledger, and the `docs/tasks/` mirrors for
  `OME-1837`, `OME-1838` and `OME-1883`.
- **Commits:** the spec and plan, then one commit per later owner decision, on branch
  `OME-1883-e5-p2-detached-run-spec`.
- **Revision, 2026-11-18 (owner decision after the code reviews):** one stop rule, in which every
  Run the Engine drives has a deadline and a follower holds an attached Run's (D10, R10, R11); the
  owner's email sealed at rest under a key only the App holds (D8, R16); the Report built once,
  when the Run ends, from the Engine's records, with the attached follow still fetching each result
  as it settles for its live score (D14, §4.6). The plan's E1, E3, E4, C1 and C2 follow.
- **Gates:** none run locally; docs only. CI runs the repo gates on the PR.
- **Deviations:** none.

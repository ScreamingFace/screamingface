---
ticket: OME-969
stack: scoreboard
status: in_progress
started: 2026-10-30
finished:
---

# Bound score submission metadata

## Intent

Apply the existing baseline metadata limits to public score submissions: at most
4096 serialized bytes and four levels deep. Authorized with OME-430 and OME-1517
on 2026-10-30; each receives a separate fix and PR.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/schemas.py`: reuse `_validate_bounded_metadata`
  in ScoreSubmission without changing baseline behavior.
- New request/schema regression tests for boundaries, nested lists, Unicode,
  normal metadata and no writes on rejection.
- Spec, plan and issue mirror.

## Test plan

Demonstrate oversized/deep requests accepted before the change. Assert field-specific
422 afterward, accepted exact boundaries and ordinary metadata round trips. Run all
scoreboard gates and existing baseline regressions.

## Acceptance

Over-limit metadata is rejected before storage. Reuse one definition of limits.
Existing valid requests and baseline import/read validation are unchanged.

## Outcome

Implementation complete; review/merge pending. Actual files match the plan.

- RED: five over-limit requests accepted; eight valid controls passed.
- GREEN: all 13 new HTTP tests pass. Combined new/baseline selection: 27 passed.
- Full scoreboard gates green: append-only tests, Ruff, formatting, Pyright,
  pytest/coverage, and portal Node tests. Existing tests unchanged.
- Commit: `fix(scoreboard): bound metadata on score submissions`.
- No migration or new dependency; no deviations.

## Wisdom review

One field validator calls the existing helper, preserving the baseline's exact
serialization and depth definitions. Tests prove both rejection without storage
and exact-boundary/Unicode round trips. No authentication, export, ranking or
stored-row behavior changes. This complements the separate OME-1658 Unicode PR;
both metadata validators must be retained when the branches are combined.

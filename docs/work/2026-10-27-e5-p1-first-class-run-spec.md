---
ticket: OME-1785
stack: repo
status: done
started: 2026-10-27
finished: 2026-10-30
---

# e5-p1-first-class-run-spec — spec and plan for E5 P1: a first-class run (id, state, history)

## Intent

Epic `OME-1294` (E5 · Improve managing runs in SF Client), priority P1. An `sf.evaluate` call
has no umbrella id, no state and no index, so a run cannot be followed, reopened or compared.
P1 is the keystone for P2 (detach, `OME-1611` + `OME-1617`) and P5 (compare). This unit
produces the spec and the plan only. No code.

## Planned changes

- `docs/spec/2026-10-27-e5-p1-first-class-run.md` (new)
- `docs/plan/2026-10-30-e5-p1-first-class-run.md` (new)
- `docs/tasks/2026-10-30-OME-1785-e5-p1-first-class-run.md` (new)
- this ledger

## Test plan

- n/a (spec only); the spec lists the tests each landing writes first.

## Acceptance

- Spec grounded in verified as-is code (file:line), contract, landings, tests, out of scope,
  and owner decisions; the owner approves the spec and the plan in plain words.

## Outcome

- **Actual files:** the spec, the plan, the `docs/tasks` mirror and this ledger.
- **Commits:** one.
- **Gates:** pre-commit hooks (docs only).
- **Deviations:** none. The stateful Engine App was approved by Irina and Kevin on `OME-1294`
  (2026-10-29), on the condition that runners stay stateless (spec §9).

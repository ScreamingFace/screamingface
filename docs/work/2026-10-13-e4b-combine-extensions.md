---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-13
finished:
---

# e4b-combine-extensions — E4b part 1 spec and plan (docs only)

## Intent

Design how 11 combine scenarios (median, mean, weighted mean, confidence picks, top-N and threshold
selections, judge argmax and argmin) run on the E4a deterministic-combine pattern, and specify the
compatible extensions that the missing scenarios need. This unit writes only the spec and the plan.
The code units follow the plan.

## Planned changes

- `docs/spec/2026-10-13-e4b-combine-extensions/` — `00-overview.md`, `erd.md`, `contracts.md`,
  `test-plan.md`, and `prd/` (catalog-and-schema, selection-input, recipes, mean, judge-order,
  weighted-median, filter-judge, pick-output).
- `docs/plan/2026-10-13-e4b-combine-extensions.md`.
- This ledger.

## Test plan

- None for this unit (docs only). The spec's test plan lists 119 TDD rows for units 1–7.

## Acceptance

- The user approves the spec and the plan.
- Every `ans:Qn` tag in the docs resolves in the overview §5 interview ledger.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** <filled at commit>
- **Gates:** repo stack only (markdown).
- **Deviations:** none.

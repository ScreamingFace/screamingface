---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
finished:
---

# e4a-gap-closure — spec and plan to meet the PRD's E4a criteria (OME-1289)

## Intent

Write the spec (ERD, PRDs, contracts, test plan) and the plan that close the E4a acceptance
gaps found when the local E4a stack was compared with the Method support v1 PRD (2026-10-01):
A1 Answer, A2 grader parity, A3 Reduce ops over signals and `filter`, A4 Fusion as a named recipe,
A6 report entries, S1 frozen schemas, and the V4 abstain decision. Documents only; code starts
after the user approves the spec and the plan in plain words.

## Planned changes

- `docs/spec/2026-10-02-e4a-gap-closure/00-overview.md`, `erd.md`, `contracts.md`, `test-plan.md`
- `docs/spec/2026-10-02-e4a-gap-closure/prd/*.md` (10 PRDs)
- `docs/plan/2026-10-02-e4a-gap-closure.md`
- this ledger

## Test plan

Documents only. The plan's per-unit gates apply when code starts.

## Notes

- Interview answers Q1–Q8 are in the spec overview §5. Q8 (fold into existing units) is against
  the recommendation.
- Code facts were read on branch `e4a-combine-hardening` with CodeGraph and file reads; Inspect
  rules were read at the locked versions inspect-ai 0.3.263 and inspect-evals 0.20.0.

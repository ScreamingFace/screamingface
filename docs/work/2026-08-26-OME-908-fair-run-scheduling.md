---
ticket: OME-908
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-08-26
finished:
---

# OME-908 — Fair scheduling of concurrent Engine runs (spec + plan)

## Intent

One large benchmark run (cold DRACO: ~20k judge calls, one provider key, up to 32 in
flight) monopolizes the gateway's 4-slot per-provider FIFO queue, so concurrent runs stall
until it drains. This unit produces the design-session inputs — a verified problem
analysis, a layered fix recommendation (engine fair budgets + a gateway companion ticket),
and a staged implementation plan — without changing any code.

## Planned changes

- `docs/spec/2026-08-26-OME-908-fair-run-scheduling.md` (new)
- `docs/plan/2026-08-26-OME-908-fair-run-scheduling.md` (new)
- `docs/tasks/2026-08-26-OME-908-fair-run-scheduling.md` (new, mirror)
- `docs/diagrams/ome-908-fair-run-scheduling.svg` + `.png` (new)

## Test plan

- None in this phase: documentation only. The spec's invariant list (section "Invariants")
  and the plan's RED stages define the tests the implementation phase must write first.

## Acceptance

- Spec and plan exist on the `OME-908-fair-run-scheduling` branch and are committed.
- The spec separates verified facts from inference, names the design options with
  trade-offs, and lists decision points D0–D5 for the design session.
- The plan stages the work RED→GREEN and names the exact files and gates.
- No application code, no Linear state change (owner acts in the design session).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** docs/spec/2026-08-26-OME-908-fair-run-scheduling.md,
  docs/plan/2026-08-26-OME-908-fair-run-scheduling.md,
  docs/tasks/2026-08-26-OME-908-fair-run-scheduling.md, docs/work/ (this file),
  docs/diagrams/ome-908-fair-run-scheduling.svg + .png
- **Commits:** see branch history (`Refs: OME-908`)
- **Gates:** n/a (docs-only phase; no stack gate applies)
- **Deviations:** none

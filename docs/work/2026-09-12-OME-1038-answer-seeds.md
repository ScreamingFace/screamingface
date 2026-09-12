---
ticket: OME-1038
stack: repo
status: in_progress
started: 2026-09-12
finished:
---

# OME-1038 — Answer-seed design session: proposal for declaring per-run seeds

## Intent

A run cannot declare answer seeds, so a published score is one sample presented as the
truth — no variance, no exact replay. This ticket is labeled `design-session`: the unit
prepares the decision material (where the seed enters the request envelope / expression
text, and the fixture-migration trade-off), and STOPS for the owner's decision. No
implementation lands in this unit.

## Planned changes

- `docs/spec/2026-09-12-answer-seeds-spec.md` — the design proposal: current-state map
  (verified 2026-09-12), the seed's entry point options, fixture-migration options
  (default-seed compatibility vs one budgeted re-record), and a recommendation.

## Test plan

- Not applicable — design-session unit; no code. The spec's claims are backed by the
  code reading recorded in the ticket ("Where — verified against the codebase 2026-09-12").

## Acceptance

- Spec in `docs/spec/` covering: seed entry point, byte-identity path, fixture-migration
  decision options with costs, don't-regress list.
- OME-1038 moved to the owner-decision STOP state with the exact question in a comment.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

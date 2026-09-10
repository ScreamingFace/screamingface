---
ticket: OME-887
stack: repo
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-887 — Make remaining activity mechanics concrete

## Intent

Prepare concrete freshness, priority-admission and bounded-decoder mechanics for the existing design review. Preserve approved ephemeral history, fixed heartbeats and the 180-second freshness threshold. No product implementation.

## Planned changes

- Spec, plan, task mirror and PR description.

## Test plan

Check current URL4 Log and Client sequence interfaces; independently review concrete algorithms, clock assumptions and bounds; validate links and diff hygiene.

## Acceptance

No unexplained freshness inference or unbounded ID state; rate priority has an exact algorithm. Compatibility and clock assumptions remain explicit proposed contract details for review.

## Outcome

- **Actual files:** spec, plan, task mirror and ledger; PR description aligned.
- **Commits:** docs: specify activity freshness and admission mechanics; Refs: OME-887.
- **Gates:** independent Standards/Spec reviews, source inspection, relative links and diff hygiene. Corrected conservative clock-skew bound to up to 60 seconds early and added both offset extremes to test plan. No runtime code changes.
- **Deviations:** none. Exact mechanisms and their clock/validation assumptions remain proposed for owner review; no product implementation or merge authorized.

---
ticket: OME-1161
stack: screamingface-engine
status: done
started: 2026-09-16
finished: 2026-09-16
---

# OME-1161 — Small activity plugin review cleanup

## Intent

Owner approved the small PR931 cleanup: remove unused heartbeat callback, name admission constants, clamp negative bridge-loss counts, and clarify reserved vocabulary. Preserve the standard-library-only emitter boundary and leave deployment wiring to PR935.

## Planned changes

- activity/scope.py: remove unused on_heartbeat parameter, storage and invocation.
- activity/session.py: name burst, refill and reserved outcome token constants without changing admission.
- activity/observer.py: clamp loss counts to [0, MAX_INTEGER].
- activity/contract.py: explain future-producer vocabulary reservation.
- Append regression tests and update existing spec/plan/mirror.

## Test plan

- RED: direct negative loss-count test; retain upper-bound and ordinary-count assertions.
- GREEN: direct plugin tests and full Engine gates, including append-only.

## Acceptance

- No unused hook; admission unchanged; loss counts nonnegative and saturated.
- No prior tests modified; no new dependency or deployment behavior.
- Push existing branch; leave PR unmerged. No Linear comments.

## Outcome

- **Actual files:** planned four activity modules, appended observer tests, existing spec/plan/task mirror and this ledger.
- **RED:** two negative-input cases failed; three zero/positive/saturation cases passed before correction.
- **GREEN:** 60 direct activity tests passed. Full Engine gates ALL GATES GREEN, including append-only, lint, format, pyright, layering, full tests and coverage (93.26%, floor 80%).
- **Wisdom:** no admission-policy changes, new dependencies, prior-test edits, or deployment wiring. Independent review found no material issues and confirmed exact reserve behavior (40 reserved + one token required = 41).
- **Commit:** fix(engine): tidy activity plugin review nits (this ledger's commit); Refs: OME-1161.
- **Deviations:** none. No Linear comments. Existing branch push leaves the PR open and starts fresh CI.

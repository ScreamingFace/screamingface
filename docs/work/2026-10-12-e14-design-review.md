---
ticket: unfiled   # leaf under OME-1307, filed at PR-open
stack: repo
status: done
started: 2026-10-12
finished: 2026-10-12
---

# e14-design-review — E14 design addendum Q23–Q30 and the review fix plan

## Intent

The owner reviewed the E14 PR stack on 2026-10-12 and raised nine items (A, B, 1–7). Each item was
checked against the code. This unit records the answers as decisions Q23–Q30 in the frozen-copy design
and adds the plan that fixes each stack branch. It also carries Q22 (capture on by default), which the
merged spec PR #1329 did not include.

## Planned changes

- `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md`: Q22 (from `c7158dad7`),
  Q23–Q30, §3, §4.2–§4.4, §5.2–§5.4 (new call key), §6, §7, §8, §9, §10 (follow-ups).
- `docs/plan/2026-10-06-e14-reproducible-submission/R-2026-10-12-design-review-fixes.md`: the fix plan.
- `docs/plan/2026-10-06-e14-reproducible-submission/F-B5-sdk-capture-reproduce.md`: Q22 (from `c7158dad7`).

## Test plan

- Docs only. The design is the rubric for the code changes in B1–C1.

## Acceptance

- Every review item maps to a decision or a follow-up, and every decision maps to a branch change.
- The owner confirms Q23–Q30 on the PR.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** the Q22 cherry-pick and one addendum commit.
- **Gates:** none (docs only).
- **Deviations:** Q27 was refined while writing the design: the occurrence counts logical calls (every
  transport attempt shares it) instead of sends, so a transport retry still replays its success. Q28
  records only the engine version, because the executor does not know the benchmark revision (the score
  already stores it). Q29 is computed by the SDK from the graded cases, because the engine run summary
  has no per-case results.
- **Interim commits (2026-10-12):** a second session pushed `1e635c5e0`, `91b352d7b` (B1) and
  `3e5ee45eb` (B3), and added plan §0a. An Opus design review of them changed the design:
  - The case key names the Attempt.
  - §3 documents `seq`, `entry_seq`, the unique `(frozen_copy, seq)` index and the error
    `response_json` shape with `Retry-After`.
  - §4.1 adds the Attempt digest rule.
  - §4.2 skips a 499 and caps the occurrence at 9 ASCII digits.
  - §4.4 re-sends the stored `Retry-After`.
  - §5.4 takes the tool occurrence before execution and keeps `max-age` re-issues `ambiguous`.
  - §0a is corrected: the `seq` uniqueness is kept, and the claim that the malformed `cache` find
    "dissolves" was wrong.

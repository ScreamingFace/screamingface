---
id: OME-1038
linear_url: https://linear.app/openmined/issue/OME-1038
status: In Progress
type: decision
priority: Low
labels: [screamingface-engine, agentic, design-session]
created: 2026-08-29
closed:
---

# A run can't declare answer seeds, so score variance can't be measured or reproduced

Design-session unit: this branch delivers the proposal only —
`docs/spec/2026-09-12-answer-seeds-spec.md` — verified against the codebase 2026-09-12.
Recommendation: seed-per-run (Option A in the spec): candidate calls mirror the judge's
existing `seed` param idiom, the spine stays untouched, an undeclared run stays
byte-identical to today so zero replay fixtures are invalidated.

Awaiting the owner's decision on the spec's three questions (option choice, no-default-seed
stance, scoreboard sub-issue timing). Implementation is a follow-up unit.

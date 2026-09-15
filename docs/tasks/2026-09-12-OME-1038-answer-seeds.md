---
id: OME-1038
linear_url: https://linear.app/openmined/issue/OME-1038
status: Done
type: decision
priority: Low
labels: [screamingface-engine, agentic, design-session]
created: 2026-08-29
closed: 2026-09-15
---

# A run can't declare answer seeds, so score variance can't be measured or reproduced

Design-session unit: this branch delivers the proposal only —
`docs/spec/2026-09-12-answer-seeds-spec.md` — verified against the codebase 2026-09-12.
Recommendation: seed-per-run (Option A in the spec): candidate calls mirror the judge's
existing `seed` param idiom, the spine stays untouched, an undeclared run stays
byte-identical to today so zero replay fixtures are invalidated.

Owner approved seed-per-run on 2026-09-12; implemented in the same branch (PR #927):
`X-Answer-Seed` header → job env → connector stamps `seed` onto every answer call
(calls pinning their own seed win — judge pass seeds never re-keyed); undeclared runs
byte-identical to today, zero fixtures re-recorded; `benchmarks/spine/` untouched.
SDK exposure (client kwarg + report field) and scoreboard mean±CI are follow-up
sub-issues per the cross-cutting rule.

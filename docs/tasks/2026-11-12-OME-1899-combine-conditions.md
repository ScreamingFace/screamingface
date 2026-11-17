---
id: OME-1899
linear_url: https://linear.app/openmined/issue/OME-1899/combine-two-conditions-in-a-gate-or-a-cascade-line-any-of-all-of
status: triage
type: improvement
priority: 4
labels: [improvement-ideas, agentic]
created: 2026-11-12
closed:
---

# Combine two conditions in a Gate or a Cascade line (any_of / all_of)

Mirror of OME-1899 (parent epic OME-1291, E4c). A follow-up idea, parked in Triage; not part of PR #1733.

A `sf.escalate_if(...)` line and a Gate `when=` take one condition. Since the 2026-11-12 product review, a failed
tier or a missing signal fails the Case unless the line is `sf.unanswered()`, so "escalate on failure OR on a low
score" cannot be written. Source: Irina's open note on flow 3 in "E4c Proposed API Flows".

Examples: COPE that also escalates when the panel fails; STEER that escalates when `lp` is low or missing; two
labels to one branch; LARGE only when the label is "hard" AND the panel disagrees.

Options: A operators `|`/`&` (operator-order trap); B `sf.any_of(...)`/`sf.all_of(...)` (recommended); C
`sf.escalate_if(c, on_failure=True)` (covers the failure cases only). Engine impact: the Gate record `when` becomes
a tree (wire change); `unanswered` is checked first; a missing signal under OR needs a rule. Landing (SDK and/or
Engine) is decided at triage.

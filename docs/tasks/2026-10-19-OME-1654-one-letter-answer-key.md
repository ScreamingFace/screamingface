---
id: OME-1654
linear_url: https://linear.app/openmined/issue/OME-1654/a-multiple-choice-answer-key-like-bc-is-accepted-as-one-option-then
status: triage
type: bug
priority: No priority
labels: [bug, screamingface-engine, agentic]
created: 2026-10-19
closed:
---

# A multiple-choice answer key like "BC" is accepted as one option, then every Case scores 0

Case Preparation compared a multiple-choice key against the letters joined into one string,
so "BC" passed as a substring of "ABCD"; inspect's `choice()` reads it as two letters, so on a
one-answer question every such Case would score 0 silently. Found in review of OME-1602 PR 5.

- 2026-10-19: fixed in `docs/work/2026-10-19-one-letter-answer-key.md`; the key is compared
  against the letters one by one.

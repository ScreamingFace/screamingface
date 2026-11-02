---
id: OME-1755
linear_url: https://linear.app/openmined/issue/OME-1755/the-judge-on-xstest-and-uccb-grades-against-the-system-prompt-plus-the
status: done
type: bug
priority: high
labels: [bug, screamingface-engine, agentic]
parent:
created: 2026-10-28
closed: 2026-10-28
---

# The judge on xstest and uccb grades against the system prompt plus the question, not the question alone

Task replay folds an eval's leading system message into the Case input, which is right for the
Candidate. Our grader built the judge's question from the same text, while inspect's judge reads
only the Sample's own input. `xstest_safe`, `xstest_unsafe` and `uccb` were off on every Case.

Fix (owner decision 2026-10-28, no opt-in, no published revision moves): on every judged row,
Case Preparation keeps the Sample's input in the Grading Material where it differs, and the
grader hands it to the judge. Only the three rows' Grading Material and Case Digest move; their
published revisions stay. The Candidate's input does not change.

- Ledger: `docs/work/2026-10-28-judge-reads-original-question.md`

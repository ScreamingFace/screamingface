---
id: OME-1906
linear_url: https://linear.app/openmined/issue/OME-1906/show-the-answer-format-each-grader-accepts-on-every-benchmark-page
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-11-13
closed:
---

# Show the answer format each grader accepts on every Benchmark page

A submitter paid for a full MMLU-Pro run whose model wrote `ANSWER: $C`, which inspect's parser
reads as no answer (OME-1886). The grader stays as inspect wrote it; instead every Benchmark's
description, which its leaderboard page shows, ends with one sentence per scorer saying what the
grader reads, and a test grades every reply the sentence quotes through each row's real grader.
No published revision or fingerprint moves.

- 2026-11-13: filed under epic `OME-1299` at PR-open. Two-PR stack: PR 1 of 2 covers the 35
  rows graded by inspect's `choice`; PR 2 of 2 the other 37 scorers (60 rows) and closes it.
- Ledger: `docs/work/2026-11-13-answer-format-choice.md`

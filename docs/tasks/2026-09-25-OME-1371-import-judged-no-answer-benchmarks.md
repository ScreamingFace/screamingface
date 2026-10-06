---
id: OME-1371
linear_url: https://linear.app/openmined/issue/OME-1371/import-judged-benchmarks-that-have-no-fixed-answer-starting-with
status: done
type: feature
priority: Medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-09-25
closed: 2026-10-01
---

# Import judged benchmarks that have no fixed answer, starting with coconot and sosbench

coconot imports as two Benchmarks: `coconot_original` (1,001 requests a model should decline,
scored by noncompliance rate through the Inverted Grade) and `coconot_contrast` (379 look-alike
requests it should answer, scored by compliance rate). Both are judged from a per-category rubric
with no answer key. Their judge answers in words (UNACCEPTABLE / ACCEPTABLE / NEITHER), so a row may
now declare `verdict_grades`, a closed word → grade map copied from the eval's own reducer; it
replaces inspect's letter map for that Benchmark and rides the revision only when set.

sosbench is not imported: its licence (CC BY-NC-SA 4.0 plus a Responsible-Use Agreement) forbids
redistribution outside the research team without written permission. That is the named blocker
the acceptance allows; it is recorded on OME-1412's unblock table.

- 2026-09-29: the no-answer-key opt-in (`has_answer_key=False`) landed with xstest in PR #1112.
- 2026-10-01: owner decisions — both coconot halves, licence odc-by, sosbench skipped on its
  licence. Spec `docs/spec/2026-10-01-coconot-verdict-grades.md`, ledger
  `docs/work/2026-10-01-coconot-import.md`.
- 2026-10-01: closed by the coconot import PR. The first paid run is the owner's (check the judge
  calls' finish reasons before trusting the scores).

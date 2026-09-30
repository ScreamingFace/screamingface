---
id: OME-1400
linear_url: https://linear.app/openmined/issue/OME-1400/score-safety-benchmarks-where-refusing-is-the-right-answer
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, human, autonomous]
parent: OME-1299
created: 2026-09-29
closed:
---

# Score safety benchmarks where refusing is the right answer

Some safety Benchmarks grade the opposite way to every other Benchmark: the eval's grade is 1
when the model went along with a prompt it should have declined. An imported Benchmark can now
declare `inverted_grade`, and each Case then scores 1 − the eval's grade, so the mean is the
refusal rate and higher stays better everywhere. The judge's own letter stays in the Check
evidence; an unscored or out-of-range grade still fails by name and is never credited as a
refusal; the flag rides the Benchmark Revision only when set, so no published revision moves.
`xstest_unsafe` (200 prompts) is the first Benchmark to use it, sharing `xstest_safe`'s judge
prompt and pinned judge. coconot and sosbench (OME-1371) reuse the same flag; the findings that
shape them are on that ticket.

- 2026-09-30: design decided on the ticket (refusal rate, no portal tag, no split); coconot and
  sosbench checked against inspect_evals source and confirmed to share the should-refuse
  direction (findings commented on OME-1371).
- 2026-09-30: PR 1 of 3 opened (branch `OME-1400-safety-refusal-score`, ledger
  `docs/work/2026-09-30-safety-refusal-score.md`, spec
  `docs/spec/2026-09-30-safety-refusal-score.md`): the flip + `xstest_unsafe`. The owner asked
  for a Benchmark-level `inverted_grade` mark in report.json (replays included), the catalogue
  and the notebook view; PRs 2–3 carry it, and the last PR closes this ticket.

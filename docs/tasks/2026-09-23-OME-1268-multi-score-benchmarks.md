---
id: OME-1268
linear_url: https://linear.app/openmined/issue/OME-1268/multi-scorers-benchmarks
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, human]
parent: OME-1299
created: 2026-09-23
closed:
---

# Multi scorers benchmarks

An inspect Task may grade each answer with several scorers (SQuAD: `f1` and `exact`; MATH:
three). The importer imports only single-scorer Tasks and a Case Grade carries one number, so
both Benchmarks are refused and a dict-valued inspect Score (SimpleQA, cyberseceval_4) fails every
Case. The change: such a Task lands as one Benchmark whose Case Grades and Candidate Result carry
every score by name in a typed `scores` field, with one declared Headline Score ranking the
Leaderboard. A scorer the Benchmark cannot express is refused or dropped by name, never silently
truncated. The field is absent on every single-scorer Benchmark, so no published Revision moves.

- 2026-09-25: owner decided one Benchmark, several scores (never one Benchmark per scorer).
- 2026-10-05: the eight design decisions settled with the owner on the ticket (typed `scores`
  field, declared headline, MATH drops its self-grading scorer by name, SimpleQA's formula
  headline needs a declared reducer with a tripwire, a `scores` block on the report card, four
  stacked code PRs with the SDK first). The ticket description is the single home; comments
  were folded in and deleted.
- 2026-10-05: docs PR opened (spec `docs/spec/2026-10-05-OME-1268-multi-score-benchmarks.md`,
  plan `docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md`, glossary entries Headline
  Score and Named Score, ledger `docs/work/2026-10-02-multi-score-boards.md`). The docs PR is
  #1235 (PR 1 of 5); code PRs 2–5 follow the plan, SDK first; the last one closes this ticket.

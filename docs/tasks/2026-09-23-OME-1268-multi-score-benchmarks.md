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
- 2026-10-06: PR 2 of 5 opened, #1248 (branch `OME-1268-sdk-named-scores`, ledger
  `docs/work/2026-10-06-ome-1268-sdk-named-scores.md`): the SDK decodes, exports and shows
  Named Scores. Needs the owner's `--skip-append-only` for the regenerated public-surface
  snapshot. Release this SDK before deploying PR 3's Engine.
- 2026-10-06: PR 3 of 5 opened, #1249 (branch `OME-1268-engine-named-scores`, stacked on
  #1248; ledger `docs/work/2026-10-06-ome-1268-engine-named-scores.md`): the Engine spine
  carries Named Scores; no importer change, no new Benchmark, every published Revision unchanged.
- 2026-10-06: PR 4 of 5 opened, #1250 (branch `OME-1268-importer-named-scores`, stacked on
  #1249; ledger `docs/work/2026-10-06-ome-1268-importer-named-scores.md`): the importer keeps
  every conservable scorer, drops a judged one by name, refuses a formula headline by name, and
  Case Preparation accepts a list of accepted answers. One prior-test fixture change needs the
  owner's `--skip-append-only`. No Benchmark row lands; PR 5 imports MATH and SQuAD.

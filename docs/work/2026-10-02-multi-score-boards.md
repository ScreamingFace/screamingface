---
ticket: OME-1268
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-05
---

# multi-score-boards — one Benchmark carrying several named scores per Case (MATH, SQuAD)

## Intent

The importer refuses any inspect Task that declares more than one scorer (MATH declares three,
SQuAD two), and the scorer adapter fails every Case whose inspect Score is a dict of named
numbers (SimpleQA, cyberseceval_4). The owner decided (OME-1268, 2026-09-25 and 2026-10-05) that
such a Task lands as ONE Benchmark whose Case Grades carry SEVERAL named scores in a typed
`scores` field, with one declared Headline Score that ranks the Leaderboard. This unit is the
docs-only first PR of a five-PR stack: the spec, the plan and the glossary entries. Code follows
in four stacked PRs (SDK decoder and report card → Engine spine → importer → MATH and SQuAD rows).

## Planned changes

- `docs/spec/2026-10-05-OME-1268-multi-score-benchmarks.md` (this PR)
- `docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md` (this PR)
- `CONTEXT.md`: glossary entries **Headline Score** and **Named Score** (this PR)
- `docs/tasks/` mirror for OME-1268 (this PR)
- code: PRs 1–4 per the plan

## Test plan

- Docs-only PR: no tests. The plan names the failing tests each code PR writes first.

## Acceptance

- Spec approved by the owner in plain words before any code PR opens.
- Plan names every file, symbol and test per code PR, with the SDK-first deploy order.
- Glossary carries the two new terms; existing entries untouched.
- Ticket OME-1268 acceptance 1–5 is reached by the four code PRs.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `docs/spec/2026-10-05-OME-1268-multi-score-benchmarks.md`,
  `docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md`, `CONTEXT.md` (two entries),
  `docs/tasks/2026-09-23-OME-1268-multi-score-benchmarks.md`, this ledger.
- **Commits:** 34502ba1d — docs(screamingface-engine): spec and plan for one Benchmark with
  several named scores
- **Gates:** docs-only, no stack gate applies; pre-commit fast hooks green; the docs/tasks ↔
  docs/work status gate (`check_mirror_status.py`) reports no new pair; both spec mermaid
  blocks rendered with `mmdc` and read (lanes stacked, no tangles).
- **Deviations:** the plan amends three spec sentences from the code recon (row fields are
  `scorer` + `extra_scorers` + `named_scores` + `dropped_scorers`, key validation sits in the
  aggregation, report.json carries `scores` as a stable key) and the spec was edited to match
  in the same commit. The code PRs are four, not three as first proposed on the ticket: the SDK
  decoder must learn the key before the Engine emits it.

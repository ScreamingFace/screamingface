---
ticket: OME-1938   # design issue ScreamingFace/screamingface#1868
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-11-17
finished: 2026-11-25
---

# btf3-local-task — serve BTF-3 (binary) as a local inspect Task

## Intent

[BTF-3](https://huggingface.co/datasets/futuresearch-ai/BTF-3) (Bench to the Future 3,
FutureSearch; CC-BY-NC-4.0) is a pastcasting benchmark of resolved forecasting questions. It is
not among the Engine's hosted Benchmarks. This unit adds its **binary** questions as a local
inspect Task, run the way the paper Diverse by Reasoning (arXiv 2608.24001) ran them: its
dataset release, its prompt and its reader, with accuracy at 0.5 as the headline and the Brier
score beside it (the design of ScreamingFace/screamingface#1868, OME-1938).

The native leaderboard lets an agent research each question in a frozen web corpus whose page
text is not distributed, so this Benchmark is closed-book: the paper's prompt with an empty
research block (the paper's "No Evidence Forecaster"). That is a named deviation.

**Process note:** an outside contribution, so the contributor filed nothing in Linear; the
ticket is the maintainer's OME-1938, which also covered FutureX-Past. This unit is its own
PR, cut from `main` (the repo squash-merges and asks not to stack PRs); it adds rows to the same
shared test tables as ScreamingFace/screamingface#1897, so whichever merges second resolves
those row conflicts.

## Planned changes

Spec `docs/spec/2026-11-17-btf3-local-task.md` and plan `docs/plan/2026-11-17-btf3-local-task.md`,
approved by the contributor on 2026-11-17 ("Approve, implement"); amendments in spec §11.

## Outcome

Built locally on 2026-11-17, not yet pushed. First built to BTF-3's native setup (A.1 prompt,
`1 - Brier`, no-forecast left out; commit `d5c8007b3`), then redesigned the same day to
ScreamingFace/screamingface#1868 (OME-1938) on the contributor's decision (spec §12): `btf3`
serves the 1,515 binary questions at `ad5a2165` with the study's prompt as sent, the study's
reader vendored verbatim, the headline accuracy at 0.5 with `brier`, `forecasts`,
`no_forecast` and `compliant` beside it, a missing forecast a miss costing Brier 0.25, and
`coverage_declare`. On 2026-11-18 the contributor reworded the study's answer line to name
the answer a probability (same `Final answer:` format; spec §12, a named deviation). Fidelity Record: re-audited against the paper's runs. On 2026-11-23, at the maintainer's request, cut as its own PR from `main`, after FutureX-Past
(#1897) merged.

Review on ScreamingFace/screamingface#2011 (2026-11-25), owner decisions and fixes:

- The seven one-row edits to existing tests are approved
  (`.claude/test-change-approvals/OME-1938.json`).
- 1,515 questions stand: the ticket's rule is the paper's commit, and 1,471 is the later
  audited release.
- A reply with no readable probability stays a miss (Brier 0.25). It is the paper's rule for a
  crowd with no decision; for one model's reply the paper drops the Case, so the row, README,
  spec and docstrings name it a deviation.
- The row is `origin="external"` and names the contributor; `paper_url` is not published,
  because BTF-3 has no paper and the authors and citation are the dataset's.
- CC-BY-NC-4.0 comes in under the worldsense precedent (decided on OME-1938).
- `case_outcome` checks 0/1 before `int()`; the vendored reader's odd reads are pinned as tests.
- The scorer's source changed, so the first id moved from `1c1d7973a6094bf4` (never published)
  to `d1102edd6f6b5c78`.

Owner-verify, not done here: `btf3` has not been run end to end against a live model, and it
is not deployed on the hosted Engine. The Fidelity Record was amended by hand on 2026-11-25,
not re-audited (the study package is local to the contributor).

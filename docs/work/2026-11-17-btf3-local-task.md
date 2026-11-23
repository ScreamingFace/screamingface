---
ticket: OME-1938   # design issue ScreamingFace/screamingface#1868; a leaf for the test-change manifest is the maintainer's call
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# btf3-local-task — serve BTF-3 (binary) as a local inspect Task

## Intent

[BTF-3](https://huggingface.co/datasets/futuresearch-ai/BTF-3) (Bench to the Future 3,
FutureSearch; CC-BY-NC-4.0) is a pastcasting benchmark of resolved forecasting questions. It is
not among the Engine's hosted Benchmarks. This unit adds its **binary** questions as a local
inspect Task, scored the native way (Brier score), with the Bench to the Future paper's own
forecaster prompt. The contributor chose binary only, Brier (2026-11-17).

The native leaderboard lets an agent research each question in a frozen web corpus whose page
text is not distributed, so this Benchmark is closed-book: the paper's prompt with an empty
research block (the paper's "No Evidence Forecaster"). That is a named deviation.

**Process note:** as for `futurex-past-local-task`, the Linear steps of the root `CLAUDE.md`
SDLC are skipped by the contributor's decision; `ticket` stays `unfiled`. This unit is its own
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
(#1897) merged. Open for the maintainer: the test-change approval manifest (OME-1938 or a
sub-issue); the issue's 1,471 vs the paper commit's 1,515; and whether a reply with no readable
probability scores 0 (as built, following #1868) or leaves the score (as the paper did).

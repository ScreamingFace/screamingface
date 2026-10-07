---
id: OME-1513
linear_url: https://linear.app/openmined/issue/OME-1513/author-a-new-benchmark-as-one-inspect-task-file-instead-of-a-hand
status: in_progress
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-07
closed:
---

# Author a new Benchmark as one inspect Task file instead of a hand-built folder

A Benchmark that is not in inspect_evals no longer needs a hand-built folder: it is written as a
**local Task** (dataset loader, scorer, `@task`) under `screamingface_engine_inspect/local_tasks/`
and fed to the same importer that imports inspect_evals. A 2026-10-07 spike proved it on MuSiQue
(180-line Task vs the closed hand-built stack's ~4,700 added lines); this ticket lands MuSiQue
that way, writes the lane rule into both onboarding docs, and lists the investigation each
remaining hand-built Benchmark needs before it moves. Replaces OME-1509, OME-1510, OME-1511.

PR 1 — MuSiQue-Ans as the first local Task: ledger
`../work/2026-10-07-OME-1513-pr1-musique-local-task.md`.

PR 1 also carries the owner rule of 2026-10-07: Draft Feedback (`with_check_surface`) is a
per-Benchmark owner decision, never a family default — importer default off, nine imported rows
and the three rubric Benchmarks turned off, IFEval the only one with the offer.

Open after PR 1: the per-Benchmark investigation comments (medxpert, draco, healthbench,
gdpval, ifeval, contracteval) and one migration PR per Benchmark that fits.

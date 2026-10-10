---
id: OME-1527
linear_url: https://linear.app/openmined/issue/OME-1527/move-each-hand-built-benchmark-to-a-local-inspect-task-or-say-why-it
status: in_progress
type: task
priority: medium
labels: [screamingface-engine, agentic, design-session]
created: 2026-10-08
closed:
---

# Move each hand-built Benchmark to a local inspect Task, or say why it stays

Six Benchmarks still live in hand-built folders (healthbench, gdpval-text, draco, ifeval,
contracteval, medxpert), so the Engine carries two serving paths for one job. Phase 1 read each
folder against the local-Task lane (OME-1513) and gave each Benchmark a verdict: medxpert stays
until OME-1521; the other five each need plugin-lane capabilities first (R1–R14 on the ticket).
Phase 2 is a Work order of about 20 PRs: the shared capabilities, then one migration PR per
approved Benchmark. The design, verdict tables and Work order live on the Linear ticket.
Supersedes OME-1508; replaces OME-1513's open acceptance item.

PR 1 of 20 — Work order #1, the importer's whole-run-metric refusal: ledger
`../work/2026-10-09-OME-1527-pr1-importer-refuses-task-metrics.md`. Owner decision 2026-10-09
(minimal): no new refusal, since inspect copies a Task-level `metrics=[...]` onto every scorer
and the existing headline check already refuses a non-mean one; the PR fixes that check's dead
pointer, drops the duplicate review TODO, and pins today's behaviour.

Open after PR 1: Work order #2 to #20 on the ticket.

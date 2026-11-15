---
id: OME-1802
linear_url: https://linear.app/openmined/issue/OME-1802/wire-the-run-registry-its-writer-and-every-outcome-producer-e5-p1-e4
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1785
created: 2026-11-02
closed:
---

# Wire the Run registry, its writer and every outcome producer (E5 P1 · E4–E6)

PR 3 of the E5 P1 Engine stack, stacked on PR 2 (`OME-1800`). It wires the Engine database
(`engine.sqlite3` locally, Postgres hosted) and the one outcome writer into the App and local
mode, adds the chart's migrate Job and limits, and makes every terminal writer publish its
Candidate's outcome when its own terminal frame landed. A hosted App without a database URL runs
with Runs off, as today.

Plan: `docs/plan/2026-10-30-e5-p1-first-class-run.md` (E4, E5, E6).
Ledger: `docs/work/2026-11-02-e5-p1-e4-wire-producers.md`.

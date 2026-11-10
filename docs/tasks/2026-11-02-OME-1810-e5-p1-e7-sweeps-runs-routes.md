---
id: OME-1810
linear_url: https://linear.app/openmined/issue/OME-1810/sweep-runs-serve-runs-and-bind-each-start-to-its-candidate-e5-p1-e7-e8
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1785
created: 2026-11-02
closed:
---

# Sweep Runs, serve /runs and bind each start to its Candidate (E5 P1 · E7–E8)

PR 4 of the E5 P1 Engine stack, stacked on PR 3 (`OME-1802`). It runs reconcile and retention at
App start and hourly, serves `/runs` (register, list, read, cancel), and binds each start to its
Run's Candidate through `X-SF-Run` and `X-SF-Run-Candidate`. With it the Engine half of P1 is
complete.

Plan: `docs/plan/2026-10-30-e5-p1-first-class-run.md` (E7, E8).
Ledger: `docs/work/2026-11-02-e5-p1-e7-sweeps-runs-routes.md`.

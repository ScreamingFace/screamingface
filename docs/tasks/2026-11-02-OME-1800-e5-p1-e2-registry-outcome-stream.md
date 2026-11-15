---
id: OME-1800
linear_url: https://linear.app/openmined/issue/OME-1800/add-the-run-registry-store-and-the-candidate-outcome-stream-e5-p1-e2e3
status: in_progress
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1785
created: 2026-11-02
closed:
---

# Add the Run registry store and the candidate outcome stream (E5 P1 · E2+E3)

PR 2 of the E5 P1 Engine stack, stacked on E1 (`OME-1797`). It adds the `RunRegistry` port and
its Tortoise store in `runs/` (SQLite and Postgres; facts only, state derived on read, writes
compare-and-set on state), and the `CandidateOutcomeStream` port with its JetStream and in-memory
adapters plus the one classifier that builds a `CandidateOutcome`. Nothing is wired.

Plan: `docs/plan/2026-10-30-e5-p1-first-class-run.md` (E2, E3).
Ledger: `docs/work/2026-11-02-e5-p1-e2-registry-outcome-stream.md`.

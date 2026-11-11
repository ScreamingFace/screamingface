---
id: OME-1815
linear_url: https://linear.app/openmined/issue/OME-1815/record-every-evaluate-as-a-run-and-add-sfruns-e5-p1-c1-c4
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1785
created: 2026-11-03
closed:
---

# Record every evaluate as a Run and add sf.runs (E5 P1 · C1–C4)

PR 5 of E5 P1, the whole Client half, from `main`. Every `evaluate` registers a Run before it
spends and binds each start to it; `Report.run_id` names it; `sf.runs` lists, reopens, waits on
and cancels Runs; `CandidateResult.run_id` is deprecated for `attempt_id`. An Engine without
`/runs` runs every `evaluate` as before, with one notice.

Plan: `docs/plan/2026-10-30-e5-p1-first-class-run.md` (C1–C4).
Ledger: `docs/work/2026-11-03-e5-p1-c1-client-runs.md`.

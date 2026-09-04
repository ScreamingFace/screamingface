---
id: OME-1121
linear_url: https://linear.app/openmined/issue/OME-1121/expose-trace-id-on-report-so-a-completed-run-can-be-quoted
status: in_progress
type: null
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-04
closed:
---

# Expose trace_id on the public result so a completed run can be quoted

First child of the Phase 1 epic (`OME-1118`). `OME-967` put the client-minted trace id on the
error hierarchy only — but a board run does not raise (DRACO collects case errors into rows),
so the user with bad results returned a clean `Report` carrying no id anywhere.

`CandidateResult.trace_id` closes it. **The field is per-candidate, not per-Report**: a
Report holds several independently executed runs, each with its own trace, exactly as it
already holds a per-run `run_id`. A single `Report.trace_id` would have to pick one.

Rung 1 of the correlation ladder is now green (**1 passed, 4 xfailed**).

Found while closing it: the ladder's own fixture named a model the synthetic tape does not
carry, so `evaluate` raised `PlanningError` in the availability probe *before the transport
ran* — no transport, no trace, and rung 1 could never have passed. A defect in `OME-1105`,
surfaced only by trying to make its rung pass.

Ledger: `docs/work/2026-09-04-OME-1121-report-trace-id.md`.

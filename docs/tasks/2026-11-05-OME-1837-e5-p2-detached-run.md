---
id: OME-1837
linear_url: https://linear.app/openmined/issue/OME-1837/p2-detach-a-run-start-it-walk-away-and-come-back-to-it
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, design-session]
parent: OME-1294
created: 2026-11-05
closed:
---

# P2 — Detach a run: start it, walk away, and come back to it

`sf.evaluate(..., detach=True)` returns a Run at once. The Engine owns it until it ends, and its
owner reattaches by `run_id` from any notebook or machine. A Run nobody comes back to stops at a
deadline. Groups `OME-1611` and `OME-1617`. Builds on P1 (`OME-1785`).

Delivered as four PRs, each with a sub-issue under this one: docs, Engine, Client, Client port.

Spec: `docs/spec/2026-11-04-e5-p2-detached-run.md`.
Plan: `docs/plan/2026-11-04-e5-p2-detached-run.md`.
Ledger: `docs/work/2026-11-04-e5-p2-detached-run-spec.md`.

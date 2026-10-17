---
id: OME-1644
linear_url: https://linear.app/openmined/issue/OME-1644/run-reviewable-notebooks-against-replay-or-local-and-pass-only-when
status: in_progress
type: feature
priority: 3
labels: [repo-dev-processes, agentic, autonomous]
created: 2026-10-17
closed:
---

# OME-1644 — Run reviewable notebooks against replay or local and pass only when the trace chain is complete

Unit 2 of epic OME-1636 (e2e notebook workbench): pytest drives generated notebooks against
`replay` or `local`; a run passes only when the notebook and the trace chain agree; each run
leaves a redacted evidence bundle.

Ledger: ../work/2026-10-16-e2e-workbench-u2-core.md

---
id: OME-861
linear_url: https://linear.app/openmined/issue/OME-861/stop-warning-when-the-engine-reports-a-total-with-no-cost-breakdown
status: In Progress
type: Feature
priority: P1
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-17
closed:
---

# Stop warning when the Engine reports a total with no cost breakdown

Part of the OME-849 cost epic. A total with no per-class breakdown became legal in OME-850 and is
what OME-851 publishes, so contract.py's total-vs-parts warning fired on every priced run.
Spec: `docs/spec/2026-08-17-OME-849-run-cost-openrouter.md`.

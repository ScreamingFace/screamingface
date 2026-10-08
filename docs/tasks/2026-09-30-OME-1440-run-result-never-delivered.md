---
id: OME-1440
linear_url: https://linear.app/openmined/issue/OME-1440/completed-runs-never-deliver-their-result-to-the-client-dev-engine
status: canceled
type: bug
priority: urgent
labels: [bug, screamingface-engine, human]
parent:
created: 2026-09-30
closed: 2026-10-01
---

# Completed runs never deliver their result to the client (dev engine)

A finished dev run never delivered its final result, and the SDK hung after
`Evaluation finished`. Filed as an engine regression after #974.

- 2026-09-30: filed.
- 2026-10-01: canceled. Not an engine fault: a test-script hook rewrote `;retry=` in the run URL4,
  so the SDK never recognised the run's root and waited forever. The SDK robustness bug is
  `OME-1451`; the hook was removed.

---
id: OME-1027
linear_url: https://linear.app/openmined/issue/OME-1027/gate-a-privacy-aware-release-must-be-the-rollback-floor-before-any
status: in_progress
type: task
priority: 2
labels: [scoreboard, human, deferred, task]
created: 2026-08-27
closed:
---

# Gate private-board activation on a privacy-aware rollback floor

Make the emergency rollback procedure executable and fail-closed: identify the rollback floor by
Helm revision plus immutable image digest, prove an export before deleting private submissions,
and verify that no private data remains before old code may serve.

The code and runbook can land independently. This issue remains open until an operator records the
production release evidence and runs the preflight inside that release's pod.

## Artifacts

- Spec: `docs/spec/2026-09-04-OME-1027-rollback-floor.md`
- Plan: `docs/plan/2026-09-04-OME-1027-rollback-floor.md`
- Ledger: `docs/work/2026-09-04-OME-1027-rollback-floor.md`

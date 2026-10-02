---
id: OME-1451
linear_url: https://linear.app/openmined/issue/OME-1451/raise-instead-of-waiting-forever-when-the-sdk-never-recognises-a-runs
status: in_review
type: bug
priority: medium
labels: [bug, client-sf, agentic]
created: 2026-10-01
closed:
---

# Raise instead of waiting forever when the SDK never recognises a run's root

The SDK must raise a clear ExecutionError when an ordered termination arrives without an
identified root. See the spec and plan dated 2026-10-02 for acceptance and implementation.

Assigned to Keelan Jordan at the owner's request. The requested delivery is a draft PR,
with the issue left In Review for human review.

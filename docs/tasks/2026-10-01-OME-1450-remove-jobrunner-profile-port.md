---
id: OME-1450
linear_url: https://linear.app/openmined/issue/OME-1450/remove-the-retired-profile-selector-from-the-url4-jobrunner-port
status: in_progress
type: task
priority: high
labels: [url4-sdk, agentic, autonomous]
parent: OME-1138
related: [OME-1449, OME-1381, OME-1394]
blocked_by: []
created: 2026-10-01
closed:
---

# Remove the retired Profile selector from the URL4 JobRunner port

The shared URL4 scheduling port still advertises `profile` even though Stage D makes every new run
selector-less. Remove the keyword from the port and its package contract tests in coordination with
the Engine implementation cleanup in `OME-1449`.

The owner confirmed on 2026-10-01 that no legacy queue messages carrying `AIGATEWAY_PROFILE`
remain and authorised full carrier removal. This is an owner-provided disposition, not a production
census claim.

## Acceptance

- `JobRunner.schedule` has no `profile` keyword.
- URL4 package tests, lint, formatting, type checking and coverage pass.
- Engine implementations satisfy the selector-less port in the coordinated landing.

## Implementation status

Implementation, review and local quality gates are complete on `OME-1449-remove-profile-carrier`.
The issue remains in progress until the coordinated landing is merged.

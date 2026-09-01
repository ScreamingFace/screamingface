---
id: OME-1066
linear_url: https://linear.app/openmined/issue/OME-1066/retry-run-submission-on-503-retry-after-instead-of-failing-the
status: planned
type: bug
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-01
closed:
---

# Retry run submission on 503 Retry-After

Parent: `OME-1064`. Blocked by `OME-1065`; must merge with or after it.

`transport.py:872` sets `permanent=response.status_code < 500`, so a 503 raises immediately
and `Retry-After` is never parsed; the existing retry ladder covers only 428. Engine-side
admission without this converts a silent hang into a fast failure rather than into a wait.

Honour `Retry-After` under a bounded total wait budget, and surface queued state through
`progress=True` so a waiting candidate reads as queued rather than hung.

Spec §4.3. Plan unit 4.

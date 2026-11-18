---
id: OME-1962
linear_url: https://linear.app/openmined/issue/OME-1962/a-sync-wait-can-hang-after-its-run-ended-because-the-disconnect-check
status: in_review
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic, autonomous]
parent:
created: 2026-11-18
closed:
---

# A sync wait can hang after its run ended, because the disconnect check swallows a cancel

Found on 2026-11-18 during the build of the chat endpoint. How and audit trail:
`docs/work/2026-11-18-wait-helper-cancel-hang.md`.

- **What:** `wait_terminal_or_gone` (`apps/screamingface-engine`, `rest/routes.py`) cancelled its
  disconnect poll task and then waited for it with no bound. Starlette's
  `Request.is_disconnected()` can swallow that cancel, so the sync `GET /?q=` and the mount calls
  could hang after the run ended. In a test, the request did not end.
- **Fix:** the race is in `rest/caller_watch.py`. The poll loop reads a `released` event, and the
  reap of the poll task is bounded. 24 new tests; no current test changed.
- **Filing:** a `bug`, so it has no epic. It is in Triage, not assigned, with Irina and Kevin
  tagged for review.

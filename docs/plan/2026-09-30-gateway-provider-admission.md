# OME-1162: implementation plan

1. Import the reviewed apps/aigateway diff without the sibling app.
2. Capture failing review regressions before any corrective runtime changes.
3. Check monotonic admission/caller deadlines after acquiring capacity. Run dispatch in the request task and let the disconnect watcher cancel that task immediately. Preserve classified errors, logging, and slot cleanup.
4. Run component gates and relevant fake-provider/transport checks.
5. Publish as a draft PR targeting main, linked to the existing component issue.

No database, dependencies, credentials, or deployment settings change.

## PR #1153 review fixes (2026-10-01)

1. Add real-socket ERROR-level logging regressions for queue/execution disconnects
   with both middleware paths, plus shutdown/concurrent cancellation coverage.
2. Mark disconnect-owned cancellation before cancelling the request task; consume
   only that cancellation at the HTTP dispatch boundary and return HTTP 499.
3. Add an optional Helm queue-timeout value, render its environment variable only
   when configured, and test the rendered configuration through Gateway Settings.
4. Document how to configure a queue timeout below existing Engine transport limits.
5. Run the existing offline component gates and chart checks, then push to PR #1153.

# OME-1163: implementation plan

1. Import the reviewed apps/screamingface-engine diff without the sibling app.
2. Capture failing review regressions before any corrective runtime changes.
3. Preserve the reviewed Engine implementation: declare phase budgets, cap by caller deadline, share the existing two-attempt retry loop, and retain spend uncertainty after transport loss. Base directly on main; merge and deploy Gateway first.
4. Run component gates and relevant fake-provider/transport checks.
5. Publish as a draft PR targeting main, linked to the existing component issue.

No database, dependencies, credentials, or deployment settings change.

Owner update, 2026-09-11: temporarily stack the integration draft on PR 899; rebase onto
main after 899 merges. Preferred remaining split: integration, then the complete activity
plugin. Integration retains the 500-line cap; plugin size will be reviewed separately.
This explicit exception supersedes the no-stack instructions below.

# OME-1161 — Docs first, then sequential code PRs

PR 897 reviews the shared design and delivery plan only. Every subsequent PR starts from
updated origin/main after its predecessor merges. No stacked PRs. Maximum 500 changed lines
per PR means additions plus deletions across production code, tests and docs, not net growth.
Check the final diff against main before opening/pushing; subdivide any unit exceeding the cap.

## Proposed code units

1. Observation ports/dispatch and unit tests (preserved source/test files total 407 lines).
2. Connector/executor/run-wrapper/composition hooks and integration tests.
3. Activity schema and bounded admission, with tests.
4. Operation scopes and heartbeat lifetime, with tests.
5. Model-call activity adapter and stream tests; subdivide if over the cap.
6. Deployment full/off policy and wiring, with tests.

These are review boundaries, not a promise to squeeze six units under the cap. Split further
where the measured diff requires it; never reduce meaningful tests to meet the line budget.
Each description retains its problem, justification, ownership, evidence and follow-up scope.

## Preserved implementation and verification

Local branches retain ports at `OME-1161-ports-preserved` (f9aa283f), integrated foundation
at `OME-1161-foundation-preserved` (1344cb62), and complete activity at
`OME-1161-activity-preserved` (01b3a0f1). All passed Engine gates before preservation.
Restore only each unit's files/tests and reconcile with merged main; never overwrite previously
landed tests. The two activity-only tests in the complete seam-test file belong with activity.
Re-run gates and review independently after each extraction; old results do not replace checks.

Use one shared spec, plan, task mirror and work ledger for OME-1161, updating these same files
across deliveries. Keep the overall ticket open until activity is delivered; the docs/interface
PRs alone do not provide researcher logging. Do not open later PRs before predecessors merge.

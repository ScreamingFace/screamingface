# OME-1161 — Sequential review units, maximum 500 changed lines each

Each PR starts from updated origin/main after its predecessor merges. No stacked PRs.
Count additions plus deletions across production, tests and docs; split further if needed.

1. Observation ports/dispatch and unit tests (PR 897).
2. Connector/executor/run-wrapper/composition hooks and integration tests.
3. Activity schema and bounded admission, with tests.
4. Operation scopes and heartbeat lifetime, with tests.
5. Model-call activity adapter and stream tests; subdivide if over the cap.
6. Deployment full/off policy and wiring, with tests.

Preserved locally: `OME-1161-foundation-preserved` at 1344cb62 (integrated foundation),
`OME-1161-activity-preserved` at 01b3a0f1 (complete activity implementation).
Restore only each unit's files/tests and reconcile with merged main; never overwrite
previously landed tests. Keep rationale in each PR and overall scope in OME-1161.
Run gates independently for every unit. Do not open later PRs before predecessors merge.

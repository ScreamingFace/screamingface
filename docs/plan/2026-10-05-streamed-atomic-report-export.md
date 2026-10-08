# Implementation plan

1. Add focused failing regressions before production changes.
2. Apply the approved source changes in an isolated worktree.
3. Run focused tests, full card gates and independent review.
4. Record evidence, reuse or file the relevant Linear issue, commit, push and publish the requested draft.

Throughput follow-up: add a deterministic Case-boundary/lazy-materialization regression,
replace scalar recursion with envelope-only streaming and standard Case encoding,
then rerun SDK gates and compare large-report throughput and auxiliary memory.

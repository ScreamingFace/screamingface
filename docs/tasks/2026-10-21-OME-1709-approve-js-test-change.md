---
id: OME-1709
linear_url: https://linear.app/openmined/issue/OME-1709/let-the-append-only-gate-approve-an-exact-js-test-change-and-run-the
status: backlog
type: task
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
parent: none (repo process)
created: 2026-10-21
closed:
---

# Let the append-only gate approve an exact .js test change, and run the approval tests

Owner-approved portal `.js` test changes get the same byte-exact manifest approval as TS/TSX and
JSON, instead of `--skip-append-only` plus `--no-verify`. The approval tests join the repo gates.
Blocks `OME-1655`.

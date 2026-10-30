---
id: OME-1791
linear_url: https://linear.app/openmined/issue/OME-1791/honor-a-custom-runner-world-config-across-local-runtime-up-and-restart
status: in_review
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1308
created: 2026-10-30
---

# Honor a custom runner world config across local runtime up and restart

External contribution PR #1553 makes `URL4_RUNNER_CONFIG` select the local runtime's complete
runner world. `restart` validates the selected file with the Engine world loader before stopping a
healthy stack. The README pairs `~` route variants with their full Gateway IDs and states that the
runner and Gateway environment variables must be re-exported for later starts.

The branch is updated to current `main`. One existing benchmark-assets test supplies the new
runtime-extra precondition without changing its assertions; the exact transition is approved in
`.claude/test-change-approvals/OME-1791.json`.

Ledger: `../work/2026-10-30-runner-config-override.md`.

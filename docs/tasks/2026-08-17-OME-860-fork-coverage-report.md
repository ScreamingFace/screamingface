---
id: OME-860
linear_url: https://linear.app/openmined/issue/OME-860/skip-the-screamingface-coverage-comment-on-fork-pull-requests
status: in_review
type: bug
priority: medium
labels: [repo-dev-processes, agentic, autonomous, bug]
created: 2026-08-17
---

# Skip the ScreamingFace coverage comment on fork pull requests

GitHub gives fork `pull_request` workflows a read-only token even when the workflow declares
`pull-requests: write`. The ScreamingFace tests and 95% coverage threshold pass, then
`orgoro/coverage` fails while trying to write a PR comment.

The coverage-comment step runs only for same-repository pull requests. Fork pull requests still run
the complete Python test and coverage command; only the unavailable write-back report is skipped.

Ledger: `../work/2026-10-30-fork-coverage-report.md`.

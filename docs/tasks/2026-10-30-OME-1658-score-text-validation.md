---
id: OME-1658
linear_url: https://linear.app/openmined/issue/OME-1658
status: in_progress
type: bug
priority: 3
labels: [scoreboard, agentic, autonomous, bug]
created: 2026-10-19
closed:
---

# Refuse unstorable text in score fields and keep 422 responses encodable

Reject NUL/lone surrogates in authors, paper_url and nested metadata before storage.
Ensure validation errors echoing malformed Unicode remain encodable 422 responses.
Test submission and editing on SQLite/PostgreSQL; preserve valid requests.

Ledger: `docs/work/2026-10-30-score-text-validation.md`.

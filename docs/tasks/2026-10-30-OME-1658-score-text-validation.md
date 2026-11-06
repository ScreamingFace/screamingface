---
id: OME-1658
linear_url: https://linear.app/openmined/issue/OME-1658
status: done
type: bug
priority: 3
labels: [scoreboard, agentic, autonomous, bug]
created: 2026-10-19
closed: 2026-11-05
---

# Refuse unstorable text in score fields and keep 422 responses encodable

Reject NUL/lone surrogates in authors, paper_url and nested metadata before storage.
Ensure validation errors echoing malformed Unicode remain encodable 422 responses.
Test submission and editing on SQLite/PostgreSQL; preserve valid requests.

Ledger: `docs/work/2026-10-30-score-text-validation.md`.

Merged [PR #1620](https://github.com/ScreamingFace/screamingface/pull/1620)
on 2026-11-03, commit `706a790fa984db16d7c06c4d64de3716c2e73428`. Linear is Done.

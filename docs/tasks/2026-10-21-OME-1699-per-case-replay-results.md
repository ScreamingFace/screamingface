---
id: OME-1699
linear_url: https://linear.app/openmined/issue/OME-1699/store-per-case-results-with-a-captured-score-so-a-failed-replay-can
status: backlog
type: feature
priority: low
labels: [scoreboard, agentic, deferred]
parent: OME-1307
created: 2026-10-21
closed:
---

# Store per-case results with a captured score so a failed replay can name the cases that differ

Follow-up from the `OME-1613` design review (owner, 2026-10-21, Q2). The board stores only a case
digest, so a failed replay reports `cases_differ` and `missed_cases` but not which cases differ.
Gate (deferred): `OME-1613` shipped and someone asks for per-case diffs.

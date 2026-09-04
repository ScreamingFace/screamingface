---
id: OME-1123
linear_url: https://linear.app/openmined/issue/OME-1123/preserve-the-created-versus-deduplicated-leaderboard-submission
status: backlog
type: null
priority: 3
labels: [py-screamingface, agentic, design-session]
created: 2026-09-04
closed: null
---

# Preserve the created-versus-deduplicated leaderboard submission outcome

The Scoreboard returns HTTP 201 when it creates a row and HTTP 200 when a submission deduplicates
onto an existing row, but the Python client currently returns only the decoded score body. Decide
on a backward-compatible public API that preserves this outcome and distinguishes creation,
same-submitter correction or replay, and deduplication onto another submitter's public row.

This is related to `OME-970`, which covers the Scoreboard returning another run's identity. The
transport signal already exists; this issue owns only the Python client's public representation.

---
id: OME-1139
linear_url: https://linear.app/openmined/issue/OME-1139/align-python-client-author-limits-with-distinct-person-semantics
status: backlog
type: task
priority: 3
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-08
closed:
---

# Align Python client author limits with distinct-person semantics

Make the Python client enforce the same author-list contract as the Scoreboard API: at most ten
case-insensitive distinct email identities and at most 4 KiB of canonical serialized author data,
without normalizing or reordering the values sent to the server.

Discovered while implementing OME-1109; kept separate because it lands in `py-screamingface`.

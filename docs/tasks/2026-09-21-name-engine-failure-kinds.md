---
id: OME-1234
linear_url: https://linear.app/openmined/issue/OME-1234/name-each-kind-of-failure-the-engine-reports-and-refuse-undeclared
status: In Progress
type: task
priority: Medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-21
closed:
parent: OME-1233
---

# Name each kind of failure the engine reports, and refuse undeclared names

Engine half of the OME-1233 epic. Split the 86-site `benchmark_unavailable` catch-all
into named failure classes (message text verbatim), reconcile the three per-board grader
spellings into one, set retryable per class, and close the name axis on the engine
`Failure` model so an undeclared name fails validation loudly instead of reaching a
report.

Lands as a stacked PR train: (a) helpers + declared list, (b) per-board
reclassification, (c) close the axis.

Full spec, evidence, and diagrams: the OME-1233 issue body.

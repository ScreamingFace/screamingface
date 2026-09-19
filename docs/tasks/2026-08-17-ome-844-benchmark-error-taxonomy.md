---
id: OME-844
linear_url: https://linear.app/openmined/issue/OME-844/split-benchmark-unavailable-into-a-real-error-taxonomy
status: Canceled
type: task
priority: Medium
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-17
closed: 2026-09-19
superseded_by: OME-1233
---

# Split benchmark_unavailable into a real error taxonomy

**Cancelled 2026-09-19 — replaced by OME-1233
(<https://linear.app/openmined/issue/OME-1233/tell-the-researcher-what-kind-of-failure-ended-their-run>).**

Not cancelled because the work shipped: the catch-all was at **86 raise sites** on
`main` `2355b968`, up from the 73 recorded here. Cancelled because the problem
statement went stale — it predates the grading spine, the per-board failure names,
and the `stage` / `retryable` axes, so its proposal named three new codes without
accounting for the ones that already exist.

OME-1233 carries the same thesis with re-verified evidence, and merges in OME-1232
(refuse undeclared failure names), which was the other half of the same change.

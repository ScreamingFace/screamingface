---
id: OME-843
linear_url: https://linear.app/openmined/issue/OME-843/capture-member-and-synthesis-output-text-in-benchmark-case-artifacts
status: In Progress
type: Feature
priority: P1
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-17
closed:
---

# Capture member and synthesis output text in benchmark case artifacts

First slice of `OME-784` (parent): persist each member and synthesis operation's raw
output text + finish_reason into the benchmark case artifact, keyed by the stable
`operation_id` from the Candidate operation projection. Motivated by the 2026-08-17
draco fusion run whose weak breadth axis (0.43) is undiagnosable from the fused answer
alone. Failure evidence / snapshots stay in `OME-784`; usage/timing attribution stays
in `OME-699`; privacy stance per `OME-316` unchanged.

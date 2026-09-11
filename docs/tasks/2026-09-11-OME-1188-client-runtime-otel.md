---
id: OME-1188
linear_url: https://linear.app/openmined/issue/OME-1188
status: In Progress
type: task
priority: High
labels: [py-screamingface, agentic, autonomous, task]
created: 2026-09-11
closed:
---

# Add bundled apps’ OpenTelemetry dependencies to the Client runtime extra

Mirror `opentelemetry-sdk>=1.30.0` and
`opentelemetry-exporter-otlp-proto-http>=1.30.0` into the Client runtime extra,
refresh its lockfile, and pass the existing dependency-parity test and Client gates.
Base Client requirements and telemetry behavior stay unchanged.

Introduced by Engine PR 905 and Gateway PR 909; exposed by CI on Client PR 918.
Deliver a separate Client packaging fix PR. Linear holds full evidence and acceptance criteria.

Implementation and draft PR authorized on 11 September 2026.

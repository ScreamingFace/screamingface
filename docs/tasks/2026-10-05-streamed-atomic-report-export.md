---
id: OME-1486
linear_url: https://linear.app/openmined/issue/OME-1486/stream-and-atomically-replace-complete-client-report-json-exports
status: in_review
type: feature
priority: P1
labels: [client-sf, agentic, autonomous]
created: 2026-10-05
closed:
---

# Stream and atomically replace complete Client report JSON exports

Child of OME-1294. Extract the first independently mergeable slice from PR #1156.

Acceptance: preserve report.v1 bytes and public API; stream case serialization; retain the previous complete destination on failure; preserve symlinks and permissions; pass all SDK gates including >=95% coverage. No persistence or notebook changes.

Implementation and validation: docs/work/2026-10-05-streamed-atomic-report-export.md.

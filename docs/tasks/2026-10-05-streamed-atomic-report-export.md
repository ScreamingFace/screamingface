---
id: OME-1486
linear_url: https://linear.app/openmined/issue/OME-1486/stream-and-atomically-replace-complete-client-report-json-exports
status: done
type: feature
priority: P1
labels: [client-sf, agentic, autonomous]
created: 2026-10-05
closed: 2026-10-08
---

# Stream and atomically replace complete Client report JSON exports

Child of OME-1294. Extract the first independently mergeable slice from PR #1156.

Acceptance: preserve report.v1 bytes and public API; stream case serialization; retain the previous complete destination on failure; preserve symlinks and permissions; pass all SDK gates including >=95% coverage. No persistence or notebook changes.

Implementation and validation: docs/work/2026-10-05-streamed-atomic-report-export.md.

Shipped in #1241 (squash-merged as `af1a10024` on 2026-10-08). Linear is Done. Umbrella OME-1448 closed on 2026-11-04.

---
id: OME-1570
linear_url: https://linear.app/openmined/issue/OME-1570/cache-compact-report-accounting-context-without-retaining-case
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
created: 2026-10-11
---

# Cache compact report accounting context without retaining Case payloads

Third SDK slice extracted from #1156, after #1241 and #1269 merged. Parent epic OME-1294; related umbrella OME-1448 and recovery OME-1503.

Stream operation/judge attribution and nullable remainder derivation. Retain only compact maps and consistency, and lazily persist a validated optional context beside saved Case indices. Preserve public accounting breakdowns, report serialization and recovery behavior. Invalid caches rebuild and write failures preserve derived values.

Acceptance: bounded evidence memory, warm disclosure without Case decoding, metadata/type/root-cost validation, exact disclosure output, all SDK gates green. Pagination/navigation and lifecycle notices remain later slices.

Spec: `docs/spec/2026-10-11-compact-accounting-context.md`; plan and work ledger use the same date/name.

---
id: OME-1117
linear_url: https://linear.app/openmined/issue/OME-1117/export-a-report-in-inspects-log-format
status: done
type: feature
priority: 4
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-04
closed: 2026-09-16
---

# Export a report in inspect's log format

One-way export from a completed client-SDK report into inspect's `.eval` log format:
`report.export(format="inspect")` writes a provenance-labeled log (produced by our
engine, real metered cost) that `inspect view` opens. Never re-imported, never a
leaderboard source. Works for home-grown-board reports too, not only imported boards.

Blocked-by relation on `OME-1115` covers only the final imported-board proof; the
export itself lands in `packages/screamingface` against report.v1 and proceeds in
parallel (owner directed start 2026-09-16).

Ledger: `docs/work/2026-09-16-OME-1117-inspect-log-export.md`

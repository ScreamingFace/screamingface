---
id: OME-951
linear_url: https://linear.app/openmined/issue/OME-951/admin-cache-snapshot-upload-epic
status: todo
type: improvement
priority: 3
labels: [aigateway, repo, autonomous, agentic]
created: 2026-08-22
closed:
---

# Admin cache-snapshot upload (epic)

Let an administrator feed a response-cache snapshot (gzip'd single-table `pg_dump` of
`request_cache_entries`, as `snapshot-cache` produces) into a deployed aigateway through the
admin console, with merge (create-or-replace) semantics, a guarded replace mode, and a
revision guard against silently-unserviceable rows.

Cross-cutting (aigateway + aigateway-ui + repo script) → this epic plus one sub-issue per
affected app/package. Never one mega-ticket.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-OME-951-admin-cache-snapshot-upload.md`
- Diagram: `docs/diagrams/ome-951-cache-snapshot-upload.svg` (+ `.png`)
- Ledger: `docs/work/2026-08-22-OME-951-admin-cache-snapshot-upload.md`
- Sub-issues: OME-952 (aigateway), OME-953 (aigateway-ui), OME-954 (repo)

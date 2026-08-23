---
id: OME-950
linear_url: # pending — owner creates the epic in Linear (MCP not active in the filing session)
status: todo
type: improvement
priority: 3
labels: [repo, autonomous, agentic]
created: 2026-08-22
closed:
---

# Admin cache-snapshot upload (epic)

PROVISIONAL id — Linear is the authority; replace this mirror's id and url when the epic exists.

Let an administrator feed a response-cache snapshot (gzip'd single-table `pg_dump` of
`request_cache_entries`, as `snapshot-cache` produces) into a deployed aigateway through the
admin console, with merge (create-or-replace) semantics, a guarded replace mode, and a
revision guard against silently-unserviceable rows.

Cross-cutting (aigateway + aigateway-ui + repo script) → this epic plus one sub-issue per
affected app/package. Never one mega-ticket.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-OME-950-admin-cache-snapshot-upload.md`
- Diagram: `docs/diagrams/ome-950-cache-snapshot-upload.svg` (+ `.png`)
- Ledger: `docs/work/2026-08-22-OME-950-admin-cache-snapshot-upload.md`
- Sub-issues: OME-951 (aigateway), OME-952 (aigateway-ui), OME-953 (repo)

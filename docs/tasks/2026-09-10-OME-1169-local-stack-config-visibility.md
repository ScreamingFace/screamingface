---
id: OME-1169
linear_url: https://linear.app/openmined/issue/OME-1169/the-local-stack-silently-ignores-the-database-setting-and-never-shows
status: in_progress
type: bug
priority: Medium
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-10
closed:
---

# The local stack silently ignores the database setting and never shows what config it started with

`AIGATEWAY_DATABASE_URL` is silently overridden by the runtime's hard-coded sqlite path, and
`screamingface up` prints nothing about its effective config — both burned paid provider calls
during the OME-1098 recordings. Fix: refuse a set `AIGATEWAY_DATABASE_URL` loudly at boot, and
print the effective gateway config (db target + request-cache state, redacted) in the ready and
adoption banners, sourced from the constructed gateway settings. Ledger:
`docs/work/2026-09-10-OME-1169-local-stack-config-visibility.md`.

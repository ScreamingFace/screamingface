---
id: OME-1048
linear_url: https://linear.app/openmined/issue/OME-1048/remediate-runtime-logs-already-on-disk-and-their-rotated-backups
status: in_review
type: bug
priority: high
labels: [client-sf, agentic, autonomous]
created: 2026-08-31
---

# Remediate runtime logs already on disk, and their rotated backups

Follow-up to OME-990. The owner decided on option (a) plus option (c), and explicitly NOT
(b):

- (a) Every start tightens the rotated backups `runtime.log.1..5` to `0600`. This is
  unconditional and chmod-only.
- (c) `screamingface logs --purge` deletes every rotated backup and empties the live log. It
  runs only when the user invokes it.

- 2026-10-01: implemented on branch `bershadsky/ome-1048-remediate-runtime-logs-already-on-disk-and-their-rotated`,
  ledger `docs/work/2026-10-01-runtime-log-remediation.md`; PR opened, In Review.

---
id: OME-1975
linear_url: https://linear.app/openmined/issue/OME-1975
status: Done
type: task
priority: Medium
labels: [client-sf, agentic, autonomous]
created: 2026-11-19
closed: 2026-11-20
---

# Keep "Key rejected" in the BYOK panel when the execution key itself is rejected

Follow-up to OME-1968 (PR #1942), from its review. A rejected execution key rejects both credit
amounts, so the BYOK panel's account box says "Key rejected" and names the management key only
when the key allowance still read. Parent: OME-1294 (E5).

Ledger: docs/work/2026-11-19-credit-reason-followup.md

Merged [PR #1955](https://github.com/ScreamingFace/screamingface/pull/1955) as `e9f8d9546`.
Linear is Done.

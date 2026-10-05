---
id: OME-1422
linear_url: https://linear.app/openmined/issue/OME-1422/prevent-large-contracteval-reports-from-crashing-the-notebook-kernel
status: in_review
type: bug
priority: high
labels: [bug, client-sf]
created: 2026-09-30
closed:
---

# Prevent large ContractEval reports from crashing the notebook kernel

Ready for review in [PR #1156](https://github.com/ScreamingFace/screamingface/pull/1156), head `8a08d4c9`: pagination-only notebook browsing, automatic durable result
retention, bounded decoding, and recovery. Combined with existing OME-1448 in PR #1156.
The source issue already exists; its Linear status remains authoritative. Validation and
validation results are recorded in the work ledger. No paid benchmark performed.

Linear reconciled to In Review on 2026-10-01. Exact padded string Case IDs are preserved before integer fallback. All SDK gates passed; 17 focused navigation tests passed. PR remains open, so this issue is not Done.

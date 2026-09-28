---
id: OME-784
linear_url: https://linear.app/openmined/issue/OME-784
status: Backlog
type: epic
priority: 2
labels: [screamingface-engine, agentic, design-session]
created: 2026-08-11
closed:
---

# Preserve failure-path and reproducibility evidence in benchmark artifacts

Linear is authoritative for the full design scope. Successful-path output/accounting slices are already delivered; do not duplicate them. Remaining scope covers failure evidence, attempts, resolved parameters, correlation and environment/config/pricing snapshots.

September 9 allocation: Engine child OME-1153 owns response diagnostics including observed status/body bytes; Gateway child OME-1154 owns successful completion and terminal duration, reusing OME-938/968/1120. Keelan coordinates the new children. Public evidence contract and any additional Client landing require design approval. OME-1127 stays open for the linked undelivered acceptance.

Audit: [OME-1127 ledger](../work/2026-09-07-OME-1127-model-call-failures.md).

---
id: OME-1116
linear_url: https://linear.app/openmined/issue/OME-1116/import-ten-single-shot-inspect-evals-benchmarks-into-the-catalogue
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-04
closed:
---

# Import ten single-shot inspect_evals benchmarks into the catalogue

A board becomes one `SnapshotSpec` row + one `BoardSpec` row (owner decision
2026-09-16 — no per-board Python modules; OME-1115's #955/#956 closed unmerged in
favor of this design). Scope: the row machine + gsm8k/mmlu re-landed as rows +
the pin-generator importer + ten new single-shot boards in batches. Also carries
OME-1115's docs close (spec §7, ledger, mirror).

Ledger: `docs/work/2026-09-16-OME-1116-import-ten-inspect-boards.md`

---
id: OME-1253
linear_url: https://linear.app/openmined/issue/OME-1253/import-every-remaining-single-turn-text-benchmark-from-inspect-evals
status: done
type: feature
priority: P2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-22
closed: 2026-09-22
---

# Import every remaining single-turn text benchmark from inspect_evals

Finish the single-turn text lane: batch-import every remaining inspect_evals
0.20.0 benchmark the importer accepts, per the ticket's 2026-09-22 full-registry
sweep (248 refs, 29 Stage-1 green, 22 in scope). 10 of the 22 are already on
main; this train imports the 7 remaining registry-`choice` boards (hellaswag,
musr, sec_qa ×2, wmdp ×3) and 4 custom-but-deterministic boards (ds1000,
class_eval, compute_eval, frontierscience) in family batches, then reconciles
all 248 refs in a scope-correction comment (image-parked, judge-scored, the two
unlock-pipe families, the offline-unresolved trio, aime2026 to product).

Ledger: `docs/work/2026-09-22-OME-1253-import-single-turn-benchmarks.md`.

Outcome: 5 boards imported (musr + wmdp ×3 in PR #1016; hellaswag + the
system-message-as-leading-input-text seam in PR #1018, stacked). ds1000 /
class_eval / compute_eval fidelity-refused (sandbox scorers), frontierscience
reclassified judge-scored, sec_qa licence-refused (owner), bbh / lingoly /
mbpp refused on online re-probe. All 248 sweep refs reconciled on the ticket;
unlock pipes follow up as OME-1264.

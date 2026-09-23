---
id: OME-1264
linear_url: https://linear.app/openmined/issue/OME-1264/import-the-lab-bench-truthfulqa-and-infinite-bench-benchmark-families
status: backlog
type: feature
priority: P2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-22
closed:
---

# Import the lab_bench, truthfulqa and infinite_bench benchmark families

18 single-turn benchmarks sit one importer extension each away from
importable: conserve `shuffle_choices` (pin a choice order as exam identity;
unlocks lab_bench ×8 + truthfulqa) and `data_files`+`features` (serialize the
schema into pins; unlocks infinite_bench ×9), then land the boards in family
batches per the adding-an-imported-benchmark runbook. Deferred out of
OME-1253 by owner sizing call (~100 LoC per extension incl. tests).

---
id: OME-1264
linear_url: https://linear.app/openmined/issue/OME-1264/shuffle-choices-data-files-features-for-hf-dataset-in-the-inspect
status: done
type: feature
priority: P2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-22
closed: 2026-09-24
---

# `shuffle_choices`, `data_files` + `features` for `hf_dataset` in the inspect importer to import the lab_bench, truthfulqa and infinite_bench benchmark families

(Retitled by owner 2026-09-23; filed as "Import the lab_bench, truthfulqa and infinite_bench benchmark families".)

18 single-turn benchmarks sit one importer extension each away from
importable: conserve `shuffle_choices` (pin a choice order as exam identity;
unlocks lab_bench ×8 + truthfulqa) and `data_files`+`features` (serialize the
schema into pins; unlocks infinite_bench ×9), then land the boards in family
batches per the adding-an-imported-benchmark runbook. Deferred out of
OME-1253 by owner sizing call (~100 LoC per extension incl. tests).

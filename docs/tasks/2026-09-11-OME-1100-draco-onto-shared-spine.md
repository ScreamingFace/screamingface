---
id: OME-1100
linear_url: https://linear.app/openmined/issue/OME-1100/fold-the-draco-5-pass-and-3-pass-boards-onto-the-shared-spine
status: done
type: refactor
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-11
closed: 2026-09-12
---

# Fold the draco 5-pass and 3-pass boards onto the shared spine

draco is the third spine copy after gdpval and healthbench: its `aggregate.py`
(484 lines) carries its own row decode, its own failure handling, and eight
`_mean_*`/`_sum_*` helpers; `case_results.py` (335 lines) assembles the typed
results. Move row decode and the failure path onto the shared spine
(`grade_case` hook from `OME-1097`); the multi-pass verdict reduction and its
metric vocabulary stay draco's, as its `grade_case` and scorer parameter.
`draco/aggregate.py` is deleted. draco proves the hook can carry a genuinely
different grading shape (N judge passes per criterion) without a sibling spine.

Guards: draco-3pass golden (100 cases, all scored, score `0.3593`) on every
rung; the seven authored failure tapes in `tests/e2e/test_failures.py`; draco
5-pass unit suite untouched and green.

Full spec: the Linear issue. Ledger:
`docs/work/2026-09-11-OME-1100-draco-onto-shared-spine.md`.

---
id: OME-1101
linear_url: https://linear.app/openmined/issue/OME-1101/fold-ifeval-onto-the-shared-spine-keeping-its-deterministic-grading-as
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-11
closed:
---

# Fold ifeval onto the shared spine, keeping its deterministic grading as its hook

IFEval's 442-line `aggregate.py` is the third hand-rolled marking room. Fold selection,
row decode, and the failure ladder onto `spine/scored.py`; ifeval keeps only its
deterministic `grade_case` hook, its published accuracy scorer, and its failure wording.
Proves the `deterministic` kind on the spine (MedXpertQA copy target, `OME-1149` dedupe).

Owner decisions: collected-error failure output stays byte-identical to the recorded
golden via one optional board-owned spine hook (also keeps the `OME-981` boundary
decision open); the exam scorer becomes a `ScoredPath` parameter.

Ledger: `docs/work/2026-09-11-OME-1101-ifeval-spine-fold.md`

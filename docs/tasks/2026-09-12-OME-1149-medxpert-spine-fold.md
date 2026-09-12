---
id: OME-1149
linear_url: https://linear.app/openmined/issue/OME-1149/adding-a-second-exact-match-benchmark-means-copying-medxpertqas
status: in_progress
type: task
priority: 4
labels: [screamingface-engine, agentic, autonomous, task]
created: 2026-09-12
closed:
---

# Adding a second exact-match benchmark means copying MedXpertQA's grading code

Shrink `medxpert/aggregate.py` (~380 lines) onto the shared `ScoredPath`: only the
letter match, the accuracy formula, and MedX's own failure wording remain. Two small
spine seams ride along: a board-named material-missing code and a per-case metadata
loader (slice tags on scored AND failed cases). The medxpert unit suite runs untouched
as the byte-identity net (no medxpert golden exists yet).

Ledger: `docs/work/2026-09-12-OME-1149-medxpert-spine-fold.md`

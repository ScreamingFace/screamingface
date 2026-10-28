---
id: OME-1479
linear_url: https://linear.app/openmined/issue/OME-1479/import-mathvista
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic]
parent: OME-1457
created: 2026-10-05
closed: 2026-10-28
---

# Import MathVista

MathVista is maths reasoning over pictures: function plots, charts, tables, geometry figures,
puzzles. inspect_evals has it (`mathvista`); since OME-1271 a Case carries its pictures, so the
importer takes it by Task replay, the LAB-Bench FigQA/TableQA pattern. Onboarding only; the
paid state-of-the-art run is OME-1673.

- 2026-10-28: `mathvista` imported by Task replay at `AI4Math/MathVista` commit `2b6ad694`
  (inspect_evals' own pin), row order forced by seed 20260917: 1,000 Cases, Case Digest
  `1f45337d…`, published revision `cc2aeecb949b920a`. No render rule of our own: the eval's
  solver ran for real, and the Sample metadata its scorer reads (`question_type`) is kept.
  Licence CC-BY-SA-4.0 from the card, accepted by the owner with the source datasets' own
  terms listed beside the row (195 NonCommercial Cases, 50 GPL-3.0, 134 unknown); it comes out
  if we go commercial. Tier `medium`, policy `withhold`. Baselines: humans 0.603 (paper,
  Table 2); Qwen3.5-397B-A17B 0.903 (its own model card, 2026-02).

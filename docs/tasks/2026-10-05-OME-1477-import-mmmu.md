---
id: OME-1477
linear_url: https://linear.app/openmined/issue/OME-1477/import-mmmu
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic]
parent: OME-1457
created: 2026-10-05
closed:
---

# Import MMMU

MMMU is a college-level exam over 30 subjects where every question carries pictures.
inspect_evals ships two tasks: multiple choice (847 questions, inspect's choice scorer) and
open (53 questions, graded by `model_graded_fact`, a judge). Onboarding only; the paid
state-of-the-art run is OME-1671.

- 2026-10-28: `mmmu_multiple_choice` imported by Task replay at `MMMU/MMMU` commit `171b0ef7`:
  847 Cases, one to five pictures each, largest Case 3.78 MB, `cases.json` 265 MB. Three
  replays (import twice, then the build path) agreed on the Case Digest, and inspect's own
  `eval()` sent byte-identical prompts and pictures for 8 sampled Cases. No importer fix was
  needed: Task replay runs the `prompt_template` then `multiple_choice` chain for real.
  Licence apache-2.0 (card header at the pin), tier `medium`, policy `withhold`.
- `mmmu_open` imported (53 Cases) but held back from the diff: the scorer adapter hands the
  judge the prompt the Candidate saw, while inspect's `model_graded_fact` reads the Sample's
  original question, so the judge's question gains the template line. Owner decision
  2026-10-28: ship multiple choice first (PR 1 of 2), and `mmmu_open` once the judge fix
  (OME-1755) lands, judged by gpt-5.4. The ticket stays open until then.

---
id: OME-1696
linear_url: https://linear.app/openmined/issue/OME-1696/add-bbh-and-medmcqa-as-benchmarks
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, human, autonomous]
parent: OME-1299
created: 2026-10-21
closed:
---

# Add BBH and MedMCQA as Benchmarks

Grantee applicants keep asking for two Benchmarks we don't have. Two PRs: BBH first, then
MedMCQA. Both are local Tasks fed to the same importer.

- PR 1: BIG-Bench Hard, 23 tasks, 6,508 Cases, 3-shot chain of thought. A local Task built
  from inspect_evals' `bbh`, because upstream's Samples carry a Python enum the Case Digest
  cannot seal. Two Named Deviations follow the paper where upstream differs: multiple choice
  asks the model to think step by step, and the 4 free-form subsets grade by exact match
  (upstream's suffix match lets wrong answers through on all 1,000 of them).
- PR 2: MedMCQA, hand-built in inspect's shape on the validation split (4,183 questions).

- 2026-10-21: owner decisions in session: local-Task wrapper for BBH (not an importer change);
  plain-mean headline (inspect's overall figure); strict paper grading on the free-form
  subsets, case-sensitive, one rule for all four; `multiple_choice(cot=True)`; one question
  (`movie_recommendation_164`, broken in the authors' own data) left out. MedMCQA: inspect's
  standard multiple-choice template, Apache-2.0 from the Hub card.

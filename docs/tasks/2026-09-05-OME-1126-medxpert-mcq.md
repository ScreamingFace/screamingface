---
id: OME-1126
linear_url: https://linear.app/openmined/issue/OME-1126/onboard-medxpertqa-text-as-an-exact-match-mcq-benchmark
status: in_progress
type: feature
priority: medium
labels: [url4-cloud, agentic, autonomous]
created: 2026-09-05
closed:
---

# Onboard MedXpertQA (Text) as an exact-match MCQ benchmark

Register the 2,450-row MedXpertQA Text test split as an Engine-owned benchmark graded by exact
letter match — no judge, zero grading tokens. Reproduces the official two-turn zero-shot CoT
protocol so scores compare to the published leaderboard. Treated as a neutral board: the prior
experiment found solos beat fusions here, and the benchmark makes no claim either way.

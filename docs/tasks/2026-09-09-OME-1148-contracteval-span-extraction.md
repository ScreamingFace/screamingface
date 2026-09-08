---
id: OME-1148
linear_url: https://linear.app/openmined/issue/OME-1148/onboard-contracteval-as-a-deterministic-span-extraction-benchmark
status: in_review
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-09
closed:
---

# Onboard ContractEval as a deterministic span-extraction benchmark

Register the CUAD test split as an Engine-owned benchmark reproducing the ContractEval protocol
(arXiv 2508.03080): the Candidate returns clause sentences verbatim or the literal
`"No related clause."`, scored by span F1/F2, Jaccard, and the false-abstain "laziness" rate,
mirrored from the paper's MIT-licensed `Evaluation.py`. No judge — zero grading tokens, the
cheapest per-row board we carry. First board with a span-overlap grader; the Engine has only
`rubric`, `exact_match` and `deterministic` today. Neutral board, as MedXpertQA was.

Ledger: `docs/work/2026-09-09-OME-1148-contracteval-span-extraction.md`

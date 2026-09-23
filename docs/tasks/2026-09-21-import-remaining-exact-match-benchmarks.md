---
id: OME-1238
linear_url: https://linear.app/openmined/issue/OME-1238/import-the-remaining-exact-match-benchmarks-the-roadmap-names
status: done
type: feature
priority: P1
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-21
closed:
---

# Import the remaining exact-match benchmarks the roadmap names

The roadmap names exact-match benchmarks the imported catalogue doesn't carry.
At the pinned inspect_evals 0.20.0 only AIME24/25, GPQA and HLE exist upstream;
MATH500, RouterBench and HotpotQA have no upstream package and TruthfulQA's
dataset mapper is refused — those go back to product as scope corrections.

Probe outcome (2026-09-22): the importer refused all four as-is — inspect_evals
0.20.0 routes `hf_dataset` through a fully-variadic retry wrapper the recorder
couldn't bind through, and AIME's prompt template lives in a shared helper
module. PR1 fixes the importer (wrapper signature fallback + VAR_KEYWORD
flattening; cross-module template resolution); PR2/PR3 land aime24/aime25 rows.
GPQA (CSV-from-URL loader at this pin — not a gated HF dataset) and HLE
(judge-graded, dataset loaded in a helper) stay refused and join the
scope-correction note on the ticket.

---
id: OME-1339
linear_url: https://linear.app/openmined/issue/OME-1339/imported-benchmarks-judge-reasoning-is-missing-from-the-notebook
status: done
type: improvement
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-09-25
closed: 2026-09-28
---

# Imported benchmarks' judge reasoning is missing from the notebook report

The inspect adapter kept a judge's words only in the evidence's `raw_output`; the report
reads `explanation`. The adapter now fills `explanation` from the same text, except when that
text is just the candidate's own answer (inspect's match, choice, pattern and math scorers
echo it). Exact-match boards change only where a scorer writes its own message (boolq's
"Scoring pattern not matched", AIME's "Model produced empty completion"), which now shows. Pairs with `OME-1340`, which lands first.

- 2026-09-25: filed.
- 2026-09-28: owner decision: fill `explanation` only when it differs from the graded answer.
  No committed replay fixture carries inspect evidence, so nothing needed re-recording.
  Implementation on branch `OME-1339-inspect-judge-explanation`.
- 2026-09-28: PR #1093 green (CI all pass). Closed on merge.

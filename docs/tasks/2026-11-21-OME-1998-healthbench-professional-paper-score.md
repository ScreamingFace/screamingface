---
id: OME-1998
linear_url: https://linear.app/openmined/issue/OME-1998/make-the-healthbench-professional-score-the-papers-score-length
status: done
type: task
priority: high
labels: [user-request, screamingface-engine, agentic, autonomous]
parent: OME-1299
created: 2026-11-21
closed: 2026-11-21
---

# Make the HealthBench Professional score the paper's score: length adjustment, low-effort judge, failed Cases count as 0

HealthBench Professional's headline sat beside two published, length-adjusted numbers but was
computed differently in three ways. It now follows
[the paper](https://arxiv.org/abs/2604.27470v1) and
[simple-evals](https://github.com/openai/simple-evals/blob/652c89d0ca9df547706735883097e9537d40dc47/healthbench_eval.py):

- each Case's rubric score is adjusted for the length of the Candidate's answer (0.0147 per 500
  characters around 2,000) before the mean and the clip;
- the judge is sent `reasoning_effort=low`;
- a Case whose Candidate call or judging failed counts as 0 over all selected Cases.

The three ship as one new published revision, `d8fb037307f35415` → `35c7d07e9058f52d`, on the
owner's sign-off. The description no longer claims the score lines up with published numbers.
healthbench-worst30 grades exactly as before and keeps its published revision.

- 2026-11-21: implemented; draft PR opened; Linear moved to In Review.
- Ledger: `docs/work/2026-11-21-healthbench-professional-paper-score.md` (the owner steps still
  pending are in its owner-verify note).
- Branch: `OME-1998-healthbench-professional-paper-score`.

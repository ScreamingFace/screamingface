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
computed differently in three ways. Its grading now:

- applies the length-adjustment formula of [the paper](https://arxiv.org/abs/2604.27470v1) and
  [simple-evals](https://github.com/openai/simple-evals/blob/652c89d0ca9df547706735883097e9537d40dc47/healthbench_eval.py)
  (0.0147 per 500 answer characters around 2,000) to each Case's value before the mean and the
  0..1 clip;
- sends the judge `reasoning_effort=low`;
- counts a Case whose Candidate call or judging failed as 0 over all selected Cases.

The three ship as one new published revision, `d8fb037307f35415` → `35c7d07e9058f52d`; the owner
approved the move. It is still not the paper's full protocol (the paper averages 8 samples per
example and uses a dated judge snapshot, and its harness never scores a failed Case 0), so the
description now says scores are not directly comparable to the published numbers.
healthbench-worst30 grades exactly as before and keeps its published revision.

The score shown on a Case stays its rubric score before the adjustment, and the adjusted value
is in the Case's evidence (owner decision, 2026-11-23: a Case score stays capped at 1, and an
adjusted value can pass it). Still open: one real judge call confirming the provider accepts the
low effort, in the ledger's owner-verify note.

- 2026-11-21: implemented; draft PR opened; Linear moved to In Review.
- 2026-11-23: review round 1 addressed (wording, the owner's decision on the Case row, judge-effort evidence).
- Ledger: `docs/work/2026-11-21-healthbench-professional-paper-score.md` (the owner steps still
  pending are in its owner-verify note).
- Branch: `OME-1998-healthbench-professional-paper-score`.

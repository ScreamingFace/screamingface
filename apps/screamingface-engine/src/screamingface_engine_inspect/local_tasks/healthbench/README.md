# HealthBench Worst-30% Challenge and HealthBench Professional

[HealthBench Professional: Evaluating Large Language Models on Real Clinician
Chats](https://arxiv.org/abs/2604.27470) (Hicks et al., 2026). 525 clinical chats, each graded
against a physician-written rubric whose lines carry points; penalty lines carry negative points.

This is a **local Task** (OME-1527): the hand-built `benchmarks/healthbench/` folder rewritten in
inspect's shape (dataset loader, scorer, whole-run metric, two `@task`s) and fed to the same
importer that imports inspect_evals. Both Benchmarks keep their ids and are ours
(`origin="screamingface"`):

| Benchmark | Cases | Headline |
|---|---|---|
| `healthbench-worst30` | the frozen hardest 157 (`subset.py`), hardest first | plain mean of the Case scores, negatives kept |
| `healthbench-professional` | all 525, in file order | the official metric: that mean clipped to 0..1 |

inspect_evals' `healthbench` is not used: it reads a different dataset (the original
HealthBench, not Professional), returns a dict Score value, and its judge sends temperature 0.0
and a system message, none of which match these Benchmarks.

## Dataset

`openai/healthbench-professional` at `349962fd` (MIT). Case ids are positions: 1..525 for
professional, as before the move; 1..157 for worst-30, where Case k is the k-th frozen id
(before the move a worst-30 Case kept its position in the 525-row file, e.g. Case 20 is now
Case 1).

## The prompt

The Candidate answers the chat with the next assistant turn. 115 of the 525 chats (43 of the
worst-30) are conversations of up to 33 turns; the rest are one user message. Capture writes a
one-message chat as its text and a conversation as the candidate-input envelope, and the row
serves every Case to the Candidate in that envelope (`candidate_input_envelope`), as the
hand-built Benchmark did: the bytes equal the hand-built `cases.json` for all 682 Cases of both
Benchmarks (compared at import), so the recorded worst-30 golden replays unchanged.

## Scoring

The rubric rides each Sample's metadata (private Grading Material). `healthbench_rubric` sends
the judge the reference grader prompt (`prompts.py`, simple-evals' `GRADER_TEMPLATE` byte for
byte) once per rubric line, as one user message with no system message:

- the judge sees the whole chat as `role: content` turns, the answer as the last assistant
  turn, and the line as `[points] criterion`;
- the reply must carry a real JSON boolean `criteria_met`; anything else is redrawn (twice at
  most, each a fresh sample outside the gateway cache, the hand-built `;retry=2`), and a line
  that still has no verdict fails the whole Case as `judge_reply_invalid`;
- the Case score is the points of the met lines over the sum of the positive points,
  unclamped (`scoring.case_score`, the reference `calculate_score`);
- worst-30's headline is the plain mean over graded Cases; professional's is
  `healthbench_clipped_mean`, the reference's `np.clip(mean, 0, 1)` over the run (clipping the
  mean is not the mean of clipped Case scores).

The reference is simple-evals' [`healthbench_eval.py` at
`652c89d`](https://github.com/openai/simple-evals/blob/652c89d0ca9df547706735883097e9537d40dc47/healthbench_eval.py),
the commit both rows cite. The `blob/main` links in the `prompts.py` and `scoring.py` headers
name the same file; they stay unpinned because editing any `.py` file here moves both
revisions and the golden (see Identity).

The judge is `openrouter/openai/gpt-5.4` (the official judge is an OpenAI-internal snapshot we
cannot reach) with no web search, a 4096 max-token cap and no temperature: the row's
`JudgeSpec`, the hand-built pins. Every judge request equals the hand-built one byte for byte
(all 1,135 prompts compared through the real connector at import).

**The Report is thinner** (owner decision, OME-1527): one Check per Case whose evidence carries
each line's points, verdict and the judge's words, the redraw count and the verdict counts; no
Check per rubric line, judge cost booked per Case, and the hand-built run metrics beside the
headline (`pass_rate`, `score_sd`, `verdict_coverage`, `judge_invalid_replies`) are not served.

## Identity

The revision hashes the Case Digest (which seals every chat and every rubric), the Task
reference, the Hub pin, the judge and its params, the envelope flag, the whole-run metric
(professional) and the sha256 of every `.py` file in this package (`task_source=…`). Editing any
of them is a new Benchmark: update the literals in
`tests/unit/inspect/test_published_revisions.py` and the healthbench-worst30 e2e golden, and say
why in the PR.

## Running it locally

```sh
# import (two clean-room replays + the two rows; already done — re-run only to re-seal)
HF_HUB_DISABLE_XET=1 uv run --extra benchmarks python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.healthbench.healthbench:healthbench_worst30 \
    --key healthbench-worst30 --no-answer-key --keep-sample-metadata
HF_HUB_DISABLE_XET=1 uv run --extra benchmarks python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.healthbench.healthbench:healthbench_professional \
    --key healthbench-professional --no-answer-key --keep-sample-metadata --whole-run-metric honour
# prepare the bundles
uv run --extra benchmarks python -m screamingface_engine.benchmarks.prepare \
    --root /tmp/assets --bundle healthbench-worst30 --bundle healthbench-professional
```

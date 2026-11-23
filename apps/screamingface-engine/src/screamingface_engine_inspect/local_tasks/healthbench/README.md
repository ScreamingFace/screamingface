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
| `healthbench-professional` | all 525, in file order | the mean of each Case's value after the paper's length adjustment, over all 525 Cases, a failed Case as 0, clipped to 0..1 |

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

**Professional applies the paper's length adjustment and low judge effort, and counts a failed
Case as 0 (OME-1998).** Three things differ from worst-30, all on the professional row only:

- **Length adjustment.** The scorer also files each Case's length-adjusted value,
  rubric score − 0.0147 × (answer characters − 2,000) / 500
  (`scoring.calculate_length_adjusted_score`, simple-evals' function of the same name, with the
  paper's constants: p.8 §4.1 writes it as s − 2.94×10⁻⁵ × (chars − 2,000)). The length is the
  Candidate's answer's, in characters. Example: rubric score 0.60, a 4,000-character answer →
  0.5412. The clipped mean averages that value. **The score shown on a Case stays its rubric
  score before the adjustment, so the mean of the Case scores shown is not the run score**
  (owner decision, 2026-11-23). The reason: an adjusted value can pass 1 (a short answer that
  meets every line is worth up to 1.0588), and a Case score may not, in the Engine or the SDK.
  That cap stays. The adjusted value and the answer's length are in the Case's evidence
  (`overall_score_length_adjusted`, `response_chars`).
- **Failed Cases count as 0.** The row's failure policy is `withhold`: a Case whose Candidate
  call or judging failed enters the clipped mean as a flat 0 (no length adjustment), over all
  selected Cases. So does an abstained Case. Coverage still reads graded / selected, and a run
  with no gradeable Case publishes no score. simple-evals never drops a Case either: it retries
  without end and grades an empty answer.
- **The judge runs at low reasoning effort**, as the paper's does (below).

worst-30 has none of the three: no adjustment, a failed Case leaves its mean, and its judge
params are the hand-built ones.

**This is not the paper's full protocol, so a score here is not directly comparable to the
published numbers.** What still differs:

- the paper averages 8 samples per example for its main results; a run here asks each Case once;
- the paper's judge is a dated GPT-5.4 snapshot; ours is OpenRouter's floating `openai/gpt-5.4`;
- simple-evals retries without end and grades whatever comes back; a failed or abstained Case
  here is a flat 0;
- the published numbers came from OpenAI's internal implementation, not simple-evals;
- the score shown on a Case is its rubric score, not the adjusted value (only the run's mean
  reads the adjusted value).

The reference is simple-evals' [`healthbench_eval.py` at
`652c89d`](https://github.com/openai/simple-evals/blob/652c89d0ca9df547706735883097e9537d40dc47/healthbench_eval.py),
the commit both rows cite. The `blob/main` links in the `prompts.py` and `scoring.py` headers
name the same file; they stay unpinned because editing any `.py` file here moves both
fingerprints (see Identity).

The judge is `openrouter/openai/gpt-5.4` (the official judge is an OpenAI-internal snapshot we
cannot reach) with no web search, a 4096 max-token cap and no temperature: each row's
`JudgeSpec`. worst-30 sends exactly the hand-built pins, so its every judge request equals the
hand-built one byte for byte (all 1,135 prompts compared through the real connector at import).
Professional also sends `reasoning_effort=low`, the paper's setting (OME-1998): its judge
prompts are the same bytes, but the request differs, so judge replies recorded before that
change no longer answer it.

**The Report is thinner** (owner decision, OME-1527): one Check per Case whose evidence carries
each line's points, verdict and the judge's words, the redraw count and the verdict counts; no
Check per rubric line, judge cost booked per Case, and the hand-built run metrics beside the
headline (`pass_rate`, `score_sd`, `verdict_coverage`, `judge_invalid_replies`) are not served.

## Identity

The fingerprint hashes the Case Digest (which seals every chat and every rubric), the Task
reference, the Hub pin, the judge and its params, the envelope flag, the whole-run metric
(professional) and the sha256 of every `.py` file in this package (`task_source=…`). Editing any of them moves only the fingerprint: `tests/unit/inspect/test_benchmark_fingerprints.py`
goes red and the Benchmark keeps publishing its hand-set `published_revision` (OME-1610).
Whether that id moves too is the owner's call, under [Changing a Benchmark's published revision](../../../../docs/adding-an-imported-benchmark.md#changing-a-benchmarks-published-revision). Both rows keep the hand-built Benchmarks' ids (OME-1527).

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

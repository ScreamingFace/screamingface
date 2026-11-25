# BTF-3 (yes/no), a local inspect Task

The yes/no questions of [BTF-3](https://huggingface.co/datasets/futuresearch-ai/BTF-3) (Bench
to the Future 3, FutureSearch), served as the Benchmark `btf3` the way the paper
[Diverse by Reasoning](https://arxiv.org/abs/2608.24001) ran them: its dataset release, its
prompt and its grading rule. Design: ScreamingFace/screamingface#1868 (OME-1938), "a replication
runs the paper's questions, prompt and grading rule, not today's". Spec:
`docs/spec/2026-11-17-btf3-local-task.md`.

| | |
|---|---|
| Key | `btf3` (origin `external`, contributor `yimingliao-blad`) |
| Data | `futuresearch-ai/BTF-3` at `ad5a2165eea26a8a43592ba36ff15765199ddc71`, `btf3_binary_questions_and_forecasts.parquet`, sha256 `50f01603…9b91c2b` |
| Cases | 1,515 (1,014 resolved No, 501 Yes); asked late April to late May 2026, expected to resolve 5 May to 1 July 2026 |
| Licence | CC-BY-NC-4.0: non-commercial use; commercial use needs FutureSearch's permission (benchmarks@futuresearch.ai) |
| Prompt | the paper's prompt (a shortened copy of Bench to the Future's Appendix A.1, research left empty) with its `Final answer:` line reworded to name a probability |
| Score | accuracy, a forecast of 0.5 or more reads Yes (headline); mean Brier beside it |
| Judge | none |
| Example | `packages/screamingface/examples/23_btf3.ipynb` |

## Why this release

It is the release the paper's study downloaded (2026-08-06), so the paper's 100 questions are
all in it: 1,515 yes/no questions. The 2026-09-15 audit release removed 119 questions (1,471
yes/no remain, the count issue #1868 quotes) and changed 3 binary resolutions; its card says
aggregate scores are not comparable across that boundary. Issue #1868 asks for the paper's
commit, so this pin wins over the quoted count. A later release is a revision bump.

## The Case

`btf3.record_to_sample` fills `PROMPT_TEMPLATE` with the row's `question`, `background`,
`resolution_criteria`, and `{today}` = the date part of `present_date` (`%Y-%m-%d`).

`PROMPT_TEMPLATE` (3,386 bytes, sha256-pinned) is the study's prompt as sent,
`bench_formats.btf_render(forecast_prompts.BTF, "tight")` from the study archive, with only its
answer line reworded (below).

- `forecast_prompts.BTF` (3,268 bytes) is a **shortened copy** of Bench to the Future's
  Appendix A.1 "No Evidence Forecaster" prompt ([arXiv 2506.21558](https://arxiv.org/abs/2506.21558);
  5,918 bytes in the e-print's `main.tex:539-611`). It keeps the structure, the tips' headings,
  steps (a) to (e) and the empty `<research>` block, and drops the worked examples, the tip
  "Sometimes there are multiple data sources…" and the parentheticals under (11).
- The study then replaced A.1's closing line ("The last thing you write is your final answer as
  a probability between 0 and 1.") with: ``End your response with exactly one line in this
  format: `Final answer: <number between 0 and 1>`. Do not write anything after that line.``
  Several small models had not reliably ended on a bare probability (18 of 18 test replies
  readable with the new line, against 6 of 18 before).
- **This Benchmark rewords that line** (contributor's decision, 2026-11-18) to:
  ``The last thing you write is your final answer as a probability between 0 and 1, on its own
  line in this format: `Final answer: <probability between 0 and 1>`. Do not write anything after
  that line.``
  A.1's line said *what* to give (a probability) but not *how*; the study's said *how* but called
  the value only "a number". Ours says both. The format is the study's, so the reader is
  unchanged. This is a named deviation (below).

Checked: all 100 of the study's stored BTF-3 prompts (`questions/btf3_100.json`) re-render
exactly from `forecast_prompts.BTF`; the test suite pins that putting the study's answer line
back gives its prompt as sent (sha256 `1b539749…`), and A.1's line gives `forecast_prompts.BTF`
(sha256 `1494ebd2…`).

Case id: `question_id`. Target and `metadata["outcome"]`: 1 for Yes, 0 for No.
`sota_forecast_probability` (FutureSearch's own forecast, 0-100) rides the metadata for
reference and is never scored.

## Reading the reply

The study's reader, `btf_parse`, vendored verbatim in `vendor/study_btf_parse.py`
(sha256-pinned), the parser every BTF-3 reply in the study went through:

1. If the last line **ends with** a probability in [0, 1] (`Final answer: 0.35`, `.35`, `0`,
   `1`, `1.0`, optionally followed by `*`, `_`, a backtick or a full stop), that is the
   forecast (`compliant: True`, `source: final_line`).
2. Otherwise the **last number in [0, 1] anywhere** in the reply is the forecast
   (`compliant: False`, `source: number_not_final`).
3. Otherwise there is **no forecast**.

Two consequences of the study's reader, kept as written:

- A percentage's own digits are never read, so `I put it at 65%.` gives no forecast. But rule 2
  then takes any stray `0` or `1` elsewhere in the reply: `About 1 month remains.` followed by
  `Final answer: 65%` is read as **1.0**.
- In rule 2, a number directly followed by a full stop is not read (the reader refuses a
  trailing `.` so as not to split `0.85`): `My answer is 0.8. But note this is uncertain.` gives
  no forecast. Rule 1 accepts the full stop, so a reply that ends `0.8.` is read.

## Scoring

The study's rules (`committee_kit/metrics.py`), as issue #1868 asks:

- **Accuracy (the headline).** A Case scores 1 when the forecast falls on the right side of one
  half, with exactly 0.5 counting as Yes, else 0.
- **Brier, beside it.** Each Score's metadata carries `brier = (f - y)^2`; the run metric
  `brier` is its mean over every Case. Lower is better; always 0.5 gives 0.25.
- **No forecast.** A reply with no readable probability, or a Candidate that abstained, is a
  **miss** (0) and costs **Brier 0.25** (read as 0.5). It stays in both means.

`btf3_headline` returns `{"accuracy", "brier", "forecasts", "no_forecast", "compliant"}`; the
row names `accuracy` the headline and the Engine publishes the rest as run metrics.
`no_forecast` counts the replies with no forecast, and `compliant` the forecasts that ended
the reply as asked. A failed Candidate call (no reply at all) leaves the denominator under
`coverage_declare`, as the study's `NO_RESPONSE` left both sides of its fraction.

Read accuracy with Brier: about two in three questions resolved No, so always answering No
already scores 0.67 on accuracy.

## Named deviations from the paper's runs

1. **All 1,515 questions**, not the paper's 100-question sample (drawn with seeds 20260808 and
   20260815, 72 No and 28 Yes).
2. **Temperature 0 is not set.** The paper ran every model at temperature 0; the Engine applies
   no Task config, so the Candidate's own settings stand. Set `temperature: 0` on the Candidate
   to match.
3. **Re-asking a cut-off reply.** The study asked again with a larger token cap; here a cut-off
   reply is read as it stands. Give the Candidate room (the prompt asks for five reasoning
   steps).
4. **The answer line is reworded** to name the answer a probability (above). The study's
   readability check and its 2,700 replies were under its own line; the effect of ours is not
   yet measured.

Against the FutureSearch leaderboard: closed-book (the leaderboard's agents research a frozen web
snapshot that is not published), binary questions only (the numeric track is out), one run per
question. The paper ran the same way, so these are not deviations from it.

## Caveats

- **Contamination.** The questions were expected to resolve between 5 May and 1 July 2026. A
  model trained after about April 2026 may know the outcomes.
- **Imbalance.** About two in three questions resolved No; compare accuracy against 0.67.
- **Resolutions.** `resolution_explanation` is machine-generated and partly spot-checked; the
  later audit release corrected 3 binary resolutions in this set.

## Run

```sh
uv run python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.btf3.btf3:btf3 --key btf3 --whole-run-metric honour
```

regenerates the catalogue rows; `tests/unit/inspect/test_local_task_btf3.py` pins the Task.

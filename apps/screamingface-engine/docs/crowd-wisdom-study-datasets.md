# The crowd-wisdom study's forecasting datasets: versions, prompt, questions, scoring

The provenance behind `futurex_past_study` and the planned BTF-3 Benchmark. This file answers four questions a maintainer asked about the study "behavior-aware LLM crowds for future
prediction", whose results these Benchmarks replicate:

1. Which Hugging Face commit of each dataset was used, and when was it downloaded?
2. What exact prompt went to the models for BTF-3?
3. Were only BTF-3's yes/no questions used, with no web search?
4. How were FutureX-Past answers scored when the answer is a number and the release gives no `std`?

**Sources.** Every answer comes from the study's own package, not from memory:
- `1_forecasting_prompts/DATASETS.md` and `btf3_prompt_template_as_sent.txt`;
- `questions/hf_download_records/` (the `huggingface_hub` download records) and
  `questions/selection_record.json`;
- `forecast_prompts.py`, `bench_formats.py` and `committee_kit/metrics.py`.

The package is the contributor's and has no public URL. Where possible, each fact was also checked
against the datasets on the Hugging Face Hub, as noted below.

## 1. Dataset versions and download dates

`huggingface_hub` keeps one record per downloaded file: the dataset commit, the file checksum and
the download time. These were the study's records:

| dataset | Hugging Face repo | commit | file used (sha256) | downloaded |
|---|---|---|---|---|
| BTF-3 | `futuresearch-ai/BTF-3` (recorded as `BTF-2/BTF-3`, which now redirects there) | `ad5a2165eea26a8a43592ba36ff15765199ddc71` (2026-07-16) | `btf3_binary_questions_and_forecasts.parquet`, `50f01603ae5284e48b462ae8855a4b5e8c82004fd07f4a3c818c0e88e9b91c2b`, 1,515 questions | 2026-08-06 01:33 UTC |
| FutureX-Past | `futurex-ai/Futurex-Past` | `3c2e39690de35eb1fcc621251f56343c72bae8c4` (2026-08-02) | `data/train-00000-of-00001.parquet`, `55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50`, 1,118 questions | 2026-08-08 01:29 UTC |

Checked against the Hub: each sha256 equals the file at that commit. The study called its models
from 2026-08-08 to 2026-08-18.

The study's questions in later releases:
- **BTF-3.** The study's 100 questions are identical (question, background, resolution criteria,
  present date, resolution) in every release from `59bf798ad8` (2026-07-15) to `4b426627e1`
  (2026-08-20). The audit release `513403f665` (2026-09-16) removed one of them,
  `c4ae196f-ebfd-58d7-a033-0bf354545620` ("Will the SEC approve the VanEck JitoSOL ETF … by June 1,
  2026?", resolved No). Releases from then on hold 99 of the 100, with the same resolutions.
- **FutureX-Past.** `3c2e3969` is the last release that holds all 100 of the study's questions.
  `36bb1cea88` (2026-08-09) removed `68774e69336fa8003b890146|2026/3/30`. The `futurex_past`
  Benchmark pins the later release `8299bfa1`, which holds 99 of them; `futurex_past_study` pins
  `3c2e3969`.

## 2. The exact BTF-3 prompt

The template is the "No Evidence Forecaster" prompt of Bench to the Future (arXiv 2506.21558,
Appendix A.1), copied verbatim into the study's `forecast_prompts.BTF`. Four placeholders are
filled from the dataset row:
- `{question}`, `{background}` and `{resolution_criteria}` come from the columns of the same names;
- `{today}` is the date part of `present_date`.

No resolution column reaches the prompt (`resolution`, `resolution_explanation`, the `sota_*`
columns). The `<research>` block stays empty, which is the paper's own setting for a forecaster
with no evidence.

**One line was changed.** The paper's closing line, "The last thing you write is your final answer
as a probability between 0 and 1.", was replaced with a fixed answer line
(`bench_formats.btf_render(..., arm="tight")`). Everything above it is unchanged. The reason: on
six test questions, three small models gave a readable answer 6 times in 18 with the original line
and 18 times in 18 with the new one, and no model got worse.

The template as sent, placeholders unfilled. This block is copied from the study's
`btf3_prompt_template_as_sent.txt`:

```text
You are a professional forecaster interviewing for a job.

Your interview question is:

You are tasked with giving a probabilistic forecast for the following question:
<question>
{question}
</question>

Here is some background on the question that you may find helpful:
<background>
{background}
</background>

The following criteria specify precisely how the question's resolution will be determined:
<resolution-criteria>
{resolution_criteria}
</resolution-criteria>

Please use the information and research gathered by your trusted assistant below:
<research>
</research>

Today is {today}.

Here are top tips from good forecasters:

If an event was anticipated to happen in a certain timeframe, but 80% of that time has passed and there is no recent news or updates about it happening soon, then you should be skeptical that it will happen in the originally stated timeframe. It probably means that it will be delayed or plans have changed.

Think about base rates for similar events in the past. Sometimes a base rate is the best you can do, if you can't find much information about the question.

Sometimes finding a good base rate is difficult, especially when the events are relatively unique. In these cases, you need to put more weight on the "inside view" which means weighing considerations that appear specific to the situation that lead to a very different forecast than base rates would dictate. You will need to use your own judgment.

Put extra weight on the status quo outcome since the world changes slowly most of the time. This is especially true when coordination or agreement between people or organizations is required.

Think about if there are seasonal effects.

Think about what the current trend is and if it makes sense to extrapolate, or not.

Think about the scope of the question.

Think about the incentives and power of any influential people involved in the situation.

(10) Pre-mortem. Think about how you are most likely to be wrong. Imagine that you are writing a letter to your future self that you will open and read once the outcome is known. In the letter you try to explain to your future self the most likely way that your forecast will be deemed to be a poor forecast. Are you most worried about missing a key piece of information? What is the biggest uncertainty and would keep you awake at night?

(11) More general advice:
 - Even if something seems impossible, think twice before forecasting less than 3%.
 - Even if something seems certain, think twice before forecasting more than 97%.
 - Pay close attention to the exact wording and resolution source in the resolution criteria.
 - Like a good forecaster, you should use your own judgment to come to the most accurate forecast!

Before answering, as part of your reasoning, you write:
(a) The time left until the outcome to the question is known.
(b) The status quo outcome if nothing changed.
(c) Think about answering the question with different scopes to help ensure that you have a self consistent view and have considered the broader context.
(d) A brief description of a scenario that results in a No outcome.
(e) A brief description of a scenario that results in a Yes outcome.

End your response with exactly one line in this format: `Final answer: <number between 0 and 1>`. Do not write anything after that line.
```

**Reading and scoring.** The probability is read from the final line. The study reports Brier (lower
is better) and accuracy, where a forecast of 0.5 or more counts as Yes.

## 3. Yes/no questions only, no web search

**Yes/no only.**
- All 100 questions come from the `binary` file. The `numeric` file and `aux/scraped_pages.parquet`
  were downloaded with the snapshot but not used.
- The 100 were drawn in two steps. First, 110 were drawn with seed 20260808, balanced by outcome
  and prompt length (`build_btf3_corpus.py`). Then 100 of those were drawn with seed 20260815,
  balanced by outcome: 72 resolved No and 28 resolved Yes.
- The second draw's seed and question ids are in `selection_record.json`.

**No web search, no tools.**
- Each call was one plain chat completion, with one user message, at temperature 0. Calls went
  through OpenRouter, and a LiteLLM gateway for a few models.
- No call carried a tool, a browsing plugin or an `:online` model variant.
- The models saw only the question, background, resolution criteria and date.
- A reply that was cut off was asked again with a larger token cap.

## 4. FutureX-Past answers that are numbers, when the release gives no `std`

**In the study, the case never came up: numeric answers were left out of the question set.**

FutureX scores a numeric answer against the standard deviation of the series. The release does not
give one, and for a figure published once a quarter it is not even defined. The study's question
set was built in three steps:
- **Training cutoff.** Only questions resolving on or after 2026-02-16 were eligible (964 of the
  1,118), so the models could not have seen an outcome in training (`build_futurex_corpus.py`).
- **First draw.** 110 questions, seed 20260808. A first selection of 100 from it contained 3
  questions whose answer is only a number (119.8, 23119 and 24.77).
- **Final draw.** That selection was replaced with a draw of 100 (seed 20260815, balanced by level)
  from only the questions that all 25 study models answered and whose answer is not purely a
  number. The rule and the reason are in `selection_record.json` (`futurex.eligibility`,
  `futurex.why`).

The final 100 are 28 questions at level 1, 47 at level 2, 16 at level 3 and 9 at level 4. Every
answer is option letters or names.

**The study's scoring** (`committee_kit/metrics.py`) never uses `std` or any tolerance:
- Answer and key are case-folded and whitespace-collapsed.
- Level 1: the answer must equal the key.
- Level 2: set F1.
- Levels 3-4: 1.0 for an exact match in order, otherwise 0.8 × overlap / k.
- The level means are weighted 10/20/30/40.

The paper's method section mentions a median rule for combining numeric answers. It never runs,
because neither question set has a numeric answer.

**In the ScreamingFace Benchmarks:**
- **`futurex_past_study`** keeps the study's rules exactly, so it reproduces the study's numbers
  (`tests/unit/inspect/test_local_task_futurex_past_study.py`).
- **`futurex_past`** serves all 2,036 questions of the later release `8299bfa1`, numeric ones
  included. It follows the FutureX authors' scorer (Futurex-Eval@2626f7a2), which scores every
  numeric key with σ = 5% of the true value (0.01 when the true value is 0):
  max(0, 1 − ((ŷ − y)/σ)²).
- That code ignores the dataset's `std` column, which is filled on only 238 rows, so a number with
  no `std` is scored the same way as one with it. The package README
  (`src/screamingface_engine_inspect/local_tasks/futurex_past/README.md`) records this, and its
  Fidelity Record (`docs/benchmarks-fidelity/futurex_past.md`) audits it.

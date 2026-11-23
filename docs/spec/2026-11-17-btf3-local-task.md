# Spec — BTF-3 (binary) as a local inspect Task

- **Unit:** `btf3-local-task` (ledger `docs/work/2026-11-17-btf3-local-task.md`)
- **Stack:** `screamingface-engine` (+ one example notebook in `packages/screamingface`)
- **Ticket:** unfiled. The contributor chose to skip Linear. No epic, issue or `Refs: OME-N`.
- **Status:** approved by the contributor (2026-11-17, "Approve, implement")

## 1. What and why

BTF-3 ([`futuresearch-ai/BTF-3`](https://huggingface.co/datasets/futuresearch-ai/BTF-3),
FutureSearch, CC-BY-NC-4.0) holds resolved forecasting questions: yes/no ("binary") and numeric.
This unit serves the **binary** questions as one Benchmark, key `btf3`, a local Task under
`screamingface_engine_inspect/local_tasks/btf3/`, imported with the existing importer like
MuSiQue and FutureX-Past (`docs/adding-an-imported-benchmark.md`). `origin="screamingface"`.

The native setup, as far as it is published (dataset card at the pin; the FutureSearch BTF-3
leaderboard at evals.futuresearch.ai; Bench to the Future, arXiv 2506.21558, §2.3–§2.5 and
Appendix A.1; BTF-2, arXiv 2604.26106):

| | Native | This Benchmark |
|---|---|---|
| Questions | binary + numeric | binary only (contributor's decision) |
| Evidence | an agent researches a frozen corpus; only its URLs and dates are published | none: closed-book (**named deviation**, §5) |
| Prompt | the paper's forecaster prompt (A.1), research filled in | the same prompt, research block empty: the paper's "No Evidence Forecaster" |
| Binary score | Brier, mean of (f − y)², lower is better | Brier, exactly (§4) |
| Runs | paper: mean of 5 runs; leaderboard: one agent run | one run (**named deviation**) |
| Code | none published | ours |

## 2. Case set (decision: all 1,515 binary questions at the study's pin)

- File `btf3_binary_questions_and_forecasts.parquet` at commit
  `ad5a2165eea26a8a43592ba36ff15765199ddc71`, sha256
  `50f01603ae5284e48b462ae8855a4b5e8c82004fd07f4a3c818c0e88e9b91c2b`. Checked: 1,515 rows,
  1,014 resolved No and 501 Yes, no duplicate `question_id`, no empty background or criteria.
  This is the release the contributor's study downloaded (2026-08-06), so the study's 100
  questions are all in it.
- Why this pin and not the latest: the 2026-09-15 audit release removed 119 questions and changed
  3 binary resolutions; the card says aggregate scores are not comparable across that boundary.
  The pin is a constant like any other; a later release is a revision bump.
- Case id: `question_id`. Target: `"1"` or `"0"` from `resolution`. Metadata:
  `present_date`, `expected_resolution_date`, `sota_forecast_probability` (nullable, 0–100,
  kept for reference only, never scored).

## 3. Prompt and reading the reply

- **Prompt:** Appendix A.1 word for word from the arXiv e-print (`main.tex:539-611`),
  `<research>` empty, `{today}` = the date part of `present_date` (`YYYY-MM-DD`, the paper's
  format). Amended 2026-11-17 (§11): not the study's copy, which turned out to be shortened. The last line is the
  paper's own: "The last thing you write is your final answer as a probability between 0 and 1."
  (The study's stricter last line is not used: native setup.) One user message, no system prompt.
- **Reading (contributor's decision, 2026-11-17: the study archive's own parser).** The paper
  gives no parser, so the reply is read with the study's `bench_formats.btf_parse`
  (`crowd-wisdom-package/1_forecasting_prompts/bench_formats.py:121-158`), the parser every
  BTF-3 reply in the study went through (`run_openrouter.py:885`), copied verbatim with
  provenance:
  1. If the reply's **last line ends with a probability** in [0, 1] (`0.35`, `.35`, `0`, `1`,
     `1.0`, optionally followed by `*`, `_`, a backtick or a full stop), that is the forecast.
  2. Otherwise the **last number in [0, 1] anywhere** in the reply is the forecast (the study
     marks it non-compliant but still uses it).
  3. Otherwise there is **no forecast**. A percentage's own digits (`65%`) are never read as
     a probability, though rule 2 then takes a stray `0` or `1` elsewhere in the reply; the paper
     filtered out values above 1 (§2.5).
  Each Score's metadata records `compliant` (rule 1) and the rule that matched, so a run shows how
  often models ended on the probability as asked.

## 4. Scoring

- Per Case: `brier = (f − y)²`, with `y` 1 for Yes and 0 for No.
- **Headline (contributor's decision, 2026-11-17: `1 − Brier`).** The platform ranks every Benchmark higher-is-better (other
  lower-is-better evals are converted, e.g. a refusal rate shown as `1 − rate`). The
  Case value is `1 − (f − y)²`, so the headline mean is **`1 − Brier`**, and the row's prose and
  README state `Brier = 1 − headline`. The raw Brier is also kept on each Score's metadata so a
  run's Brier can be read directly.
- **No forecast (contributor's decision, 2026-11-17: left out, as native).** It is **left out of
  the headline, following the paper's filtering of unusable forecasts** (§2.5; dropped
  questions shrink N), with the count of left-out Cases shown through
  `coverage_declare`. (The study instead scored a missing forecast as 0.5, Brier 0.25; that is
  not native.) The headline is a whole-run metric (mean over Cases with a forecast), so the row
  honours a whole-run metric and the failure policy is `coverage_declare` (OME-1642), as
  `futurex_past_study` does.

## 5. Named deviations (on the row and in the README)

1. Closed-book: no research corpus; the paper treats this mode as a baseline, so scores are not
   comparable with the leaderboard's agents.
2. One run per question, not the paper's mean of 5.
3. Binary only; the numeric track (experimental, scored by an unpublished normalised RPS) is out.
4. The reply parser is the contributor's study parser (§3); the paper publishes none.

## 6. Generation

`generate()` with the Candidate's defaults; no temperature is pinned (the paper names none).
Contamination: questions expected to resolve 5 May to 1 July 2026; the card warns that models with a
training cutoff after about April 2026 may have seen outcomes. Stated on the row and README.

## 7. Failure policy, Draft Feedback, revision

`coverage_declare` (whole-run metric). Draft Feedback off. Published revision
from `benchmark_bump.py`. Example notebook `packages/screamingface/examples/23_btf3.ipynb` (22 is
FutureX-Past's in ScreamingFace/screamingface#1897; whichever merges second renumbers if needed).

## 8. Licence (owner decision)

BTF-3 is CC-BY-NC-4.0: "commercial use requires permission: benchmarks@futuresearch.ai" (current
card). The Task downloads the file at run time and redistributes nothing, but serving it as a
ScreamingFace Benchmark may count as commercial use. The PR asks the owners to decide or to seek
FutureSearch's permission; the README states the licence.

## 9. Out of scope

The numeric questions; the scraped-pages corpus; any research agent; the study's 100-question
subset and its stricter prompt (a study Benchmark like `futurex_past_study` can follow if wanted).

## 10. Process notes

Linear skipped (as for FutureX-Past). Shared test tables (stand-in metadata, declaration, family,
failure policy, published revision, fingerprint, whole-run metric, answer format) each gain one
row; the append-only gate needs an `OME-N` approval file, drafted in the PR description.

## 11. Amendments during implementation (2026-11-17)

- **The prompt is the paper's A.1 word for word, not the study's copy.** The fidelity audit (D5)
  compared the study's `forecast_prompts.BTF`, which this spec first called "A.1 verbatim", with
  the arXiv e-print (`main.tex:539-611`): the study's copy is shortened (3,268 bytes against
  5,918; the paper's examples, one tip and the parentheticals under (11) dropped; one word
  changed). Following the contributor's "native setup" decision, the Task serves the paper's text.
  The study's 100 prompts therefore no longer re-render, and that test was dropped.
- **The outcome rides the metadata** (`metadata["outcome"]`), which the scorer reads and fails
  loudly without: the no-network lanes give every Benchmark a placeholder target.
- **Wording:** the "left out" rule follows the paper's filtering (§2.5), which removed 11 forecasts
  above 1; the leaderboard states no such rule. A percentage's digits are never read, but the
  reader's second rule then takes a stray `0` or `1`.
- **The left-out count is published** (code review; the maintainer asked the same of
  `futurex_past_study` on OME-1952). Leaving a Case out keeps it graded, so coverage alone never
  showed it. `btf3_headline` returns `{"one_minus_brier", "forecasts", "no_forecast",
  "compliant"}`, the row names `one_minus_brier` its `whole_run_headline`, and the three counts
  are published as run metrics.
- **A resolution other than 0 or 1 is refused** at load, so a future pin cannot floor 0.5 to No.

## 12. Redesign to issue #1868 (2026-11-17, contributor's decision: "Follow issue #1868")

The maintainer's design for this Benchmark is ScreamingFace/screamingface#1868 (Linear
OME-1938): "A replication runs the paper's questions, prompt and grading rule, not today's",
where "the paper" is the contributor's *Diverse by Reasoning* (arXiv 2608.24001). The
contributor chose that design over the native setup above. **This section supersedes §1's table,
§3's prompt, §4 and §5 wherever they disagree.**

- **Prompt: the study's prompt as sent.** `bench_formats.btf_render(forecast_prompts.BTF,
  "tight")`, byte for byte (3,325 bytes, sha256 `1b539749…`): the study's shortened copy of A.1
  with A.1's closing line replaced by the study's `Final answer: <number between 0 and 1>` line.
  All 100 of the study's stored prompts re-render from `forecast_prompts.BTF` and the pinned file.
  **Amended 2026-11-18 (contributor's decision):** the answer line is reworded to "The last thing
  you write is your final answer as a probability between 0 and 1, on its own line in this
  format: `Final answer: <probability between 0 and 1>`. Do not write anything after that line."
  (3,386 bytes, sha256 `62f19370…`), so the line names the answer a probability. The format, and
  so the reader, is unchanged; putting the study's line back gives its prompt as sent (pinned).
  A named deviation.
- **Headline: accuracy at 0.5** (exactly 0.5 reads Yes), over every Case. **Brier beside it**
  as the run metric `brier`, with `forecasts`, `no_forecast` and `compliant`.
- **No forecast: a miss, Brier 0.25**, the study's rule (`committee_kit/metrics.py`,
  `ABSTAIN_BRIER`) and the issue's F1 ("Case scores 0 under the abstain rule, count shown in the
  report"). A failed call with no reply leaves the denominator (`coverage_declare`), as the
  study's `NO_RESPONSE` did.
- **Questions: 1,515, not the issue's 1,471.** The issue quotes the post-audit count but also
  asks for the paper's commit; the paper's commit (`ad5a2165`, downloaded 2026-08-06) holds
  1,515. Flagged on the PR for the maintainer.
- **Temperature.** The study ran at temperature 0. The Engine applies no Task config, so the Task
  sets none and the row names it a deviation (set it on the Candidate).
- **Named deviations from the paper's runs:** all 1,515 questions, not its 100-question sample;
  temperature not set; a cut-off reply is not re-asked; the answer line reworded (2026-11-18). Closed-book, binary-only and one run per
  question match the paper.
- Renamed: scorer `btf3_brier` → `btf3_accuracy`; headline key `one_minus_brier` → `accuracy`;
  `paper_url` → arXiv 2608.24001.

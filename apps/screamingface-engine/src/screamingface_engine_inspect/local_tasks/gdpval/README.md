# GDPval Text Subset

[GDPval: Evaluating AI Model Performance on Real-World Economically Valuable
Tasks](https://arxiv.org/abs/2510.04374) (Patwardhan et al., OpenAI, 2025). The prose-only slice
of the 220-task open gold set: 102 professional work requests whose reference material and
expected deliverable are documents rather than spreadsheets or slide decks.

This is a **local Task** (OME-1527): the hand-built `benchmarks/gdpval/` folder rewritten in
inspect's shape (dataset loader, scorer, one `@task`) and fed to the same importer that imports
inspect_evals. The Benchmark keeps its id, `gdpval-text`, and is ours (`origin="screamingface"`).
inspect_evals' own `gdpval` is a different exam (agentic, in a sandbox, all 220 tasks); it is
not imported.

## Dataset

`openai/gdpval` at `11e7900c` ("Release GDPval v2", the commit that added `rubric_json`). No
licence is stated on the card or README. The frozen selection is `subset.py`: 109 prose-only
tasks minus the 7 whose reference files do not extract to text, in a fixed order (the Case ids
are positions in it).

36 of the 102 tasks carry reference files (58 in all). The loader downloads each once, from the
URL the row gives on the dataset's moving branch, and flattens it to text with pdfplumber or
python-docx (`references.py`, the `benchmarks` extra; build time only). Those URLs are not
pinned, exactly as before the move: a changed file changes the flattened text, which breaks the
Case Digest. A PR image build then fails; a main or release build skips gdpval-text with a
warning in the build log and serves the other Benchmarks.

## The prompt

One user message: the request, then for each reference file a `--- Reference file: <name> ---`
line and its text, joined by blank lines. The bytes equal the hand-built Benchmark's for all
102 Cases (compared at import).

## Scoring

The rubric rides each Sample's metadata (private Grading Material), after `rubric_filter.py`
drops the criteria that judge the delivered file rather than its content (106 of 4,553; the
4,447 left are numbered from 1). `gdpval_rubric` asks the judge about one criterion at a time
with the hand-built grader prompt (`prompts.py`), one call per criterion, about 44 per Case:

- the judge must answer with a JSON boolean `criteria_met`; anything else is redrawn (twice at
  most, each a fresh sample outside the gateway cache), then the Case fails as
  `judge_reply_invalid` — never scored on a partial rubric;
- Case score = points of the met criteria (penalties subtract) over the positive points, with
  no clamp, so a Case can score below zero;
- the headline is the plain mean over graded Cases.

The judge is `openrouter/google/gemini-3.1-pro-preview` at temperature 0.2, reasoning effort
low, 8192 max tokens, no web search: the row's `JudgeSpec`, the hand-built pins.

**The Report is thinner than the hand-built one** (owner decision, OME-1527): one Check per
Case, whose evidence carries each criterion's id, points, verdict and the judge's words, plus
the redraw count; no Check per criterion, and judge cost is booked per Case. The criterion text
stays out of the Report (it is private Grading Material). The hand-built run metrics
`pass_rate`, `verdict_coverage`, `score_sd` and `judge_invalid_replies` are not served.

## Identity

The revision hashes the Case Digest (which seals every prompt and every filtered rubric), the
Task reference, the Hub pin, the judge and its params, and the sha256 of every `.py` file in
this package (`task_source=…`). Editing any of them is a new Benchmark: update the literal in
`tests/unit/inspect/test_published_revisions.py` and say why in the PR.

## Running it locally

```sh
# import (two clean-room replays + the two rows; already done — re-run only to re-seal)
HF_HUB_DISABLE_XET=1 uv run --extra benchmarks python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.gdpval.gdpval:gdpval_text \
    --key gdpval-text --no-answer-key --keep-sample-metadata
# prepare the bundle
uv run --extra benchmarks python -m screamingface_engine.benchmarks.prepare \
    --root /tmp/assets --bundle gdpval-text
```

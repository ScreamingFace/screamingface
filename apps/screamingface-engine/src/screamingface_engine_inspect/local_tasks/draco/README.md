# DRACO and DRACO 3-Pass

[DRACO: a Cross-Domain Benchmark for Deep Research Accuracy, Completeness, and
Objectivity](https://arxiv.org/abs/2602.11685) (Zhong et al., Perplexity, 2026). 100 open-ended
deep-research questions, each graded against an expert-written rubric of about 40 weighted
criteria.

This is a **local Task** (OME-1527): the hand-built `benchmarks/draco/` folder rewritten in
inspect's shape (dataset loader, scorer, two `@task`s) and fed to the same importer that imports
inspect_evals. Both Benchmarks keep their ids, `draco` (five judge passes, the paper's stability
protocol) and `draco-3pass` (three), and are ours (`origin="screamingface"`). inspect_evals has
no DRACO.

## Dataset

`perplexity-ai/draco` at `ce076749` (MIT), all 100 rows in dataset order; the Case ids are
positions in it (1..100), as before the move.

## The prompt

The Candidate is sent the `problem` column untouched, as one user message: the bytes equal the
hand-built Benchmark's for all 100 Cases (compared at import). The Candidate may search the web:
the row's retrieval policy (`draco/reproduction`) turns search on and bans the seven hosts that
publish DRACO's answers (arxiv.org, huggingface.co, openrouter.ai, paperswithcode.com,
alphaxiv.org, semanticscholar.org, research.perplexity.ai). The list is a host-only floor, not
the paper's page-shaped blocklist: the provider refuses anything longer than a host.

## Scoring

The weighted rubric rides each Sample's metadata (private Grading Material). `draco_rubric`
asks the judge about one criterion at a time, once per pass, with the paper's Appendix C.5
instructions (`prompts.py`):

- the judge sees the criterion, whether it is positive or negative, the question and the
  answer, never its weight;
- pass `k` is stamped `seed=k`, so the passes are separate requests and the gateway cache cannot
  answer them all with one reply;
- the reply must be JSON with a `criterion_status` of exactly `MET` or `UNMET` and an
  explanation; anything else is redrawn (twice at most, each a fresh sample outside the gateway
  cache), and if it still has no verdict that criterion is left out of that pass;
- each pass scores `clamp(Σ weight of met criteria / Σ positive weights, 0, 1)` (a met
  negative criterion subtracts); the Case score is the mean over the passes, to 4 places;
- a Case with no valid verdict at all fails as `judge_reply_invalid`, never scored 0; the
  headline is the mean over graded Cases, to 4 places.

The judge is `openrouter/google/gemini-3.1-pro-preview` (the paper's Gemini-3-Pro Preview was
shut down; Google named this its successor) at temperature 0.2, reasoning effort low, 4096 max
tokens, no web search: the row's `JudgeSpec`, the hand-built pins.

**Two deliberate differences from the hand-built grader.** A reply with no verdict is redrawn
before its criterion is left out of the pass (the hand-built grader asked once). And the Report
is thinner (owner decision, OME-1527): one Check per Case, whose evidence carries each
criterion's per-pass verdicts and the judge's words, the redraw count, the pass rate, the
per-axis scores and the verdict counts; no Check per criterion, and judge cost is booked per
Case. A judge call that fails outright (a token cap, a 429 past its retries) fails the Case as
`scorer_error`, its cause in that Check's evidence.

## Identity

The revision hashes the Case Digest (which seals every question and every rubric), the Task
reference, the Hub pin, the judge and its params, the seed per pass, the retrieval policy, and
the sha256 of every `.py` file in this package (`task_source=…`). Editing any of them is a new
Benchmark: update the literals in `tests/unit/inspect/test_published_revisions.py` and the
draco-3pass e2e golden, and say why in the PR.

## Running it locally

```sh
# import (two clean-room replays + the two rows; already done — re-run only to re-seal)
HF_HUB_DISABLE_XET=1 uv run --extra benchmarks python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.draco.draco:draco_3pass \
    --key draco-3pass --no-answer-key --keep-sample-metadata \
    --retrieval-policy draco/reproduction --retrieval-excluded-domain arxiv.org  # …all seven
# prepare the bundles
uv run --extra benchmarks python -m screamingface_engine.benchmarks.prepare \
    --root /tmp/assets --bundle draco --bundle draco-3pass
```

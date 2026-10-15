# FRAMES, articles given

[Fact, Fetch, and Reason: A Unified Evaluation of Retrieval-Augmented Generation](https://arxiv.org/abs/2409.12941)
(Krishna et al., 2024). 824 questions, each answerable only by combining facts from 2 to 23
Wikipedia articles: numbers, tables, several constraints, dates, and post-processing. This is
the paper's **Oracle** setting: every question comes with its gold articles pasted into the
prompt, so nothing is searched and the score measures reading and reasoning, not retrieval.

This is a **local Task** (OME-1481): an eval we author in inspect's shape (dataset loader,
scorer, one `@task`) and feed to the same importer that imports inspect_evals. FRAMES is not in
inspect_evals; the Benchmark it produces is ours (`origin="screamingface"`).

## Dataset

Two Hugging Face sources, each pinned by commit and sha256-checked before a byte is parsed:

| Source | File | What it gives |
| -- | -- | -- |
| `google/frames-benchmark` @ `58d9fb63` | `test.tsv` | the 824 questions, their gold answers and reasoning types (Apache-2.0) |
| `khoaguin/frames-wikipedia-2024-09-19` @ `6ada7fb7` | `questions.jsonl`, `articles.jsonl` | each question's gold articles, frozen at their last revision before 2024-09-19 (CC BY-SA 4.0) |

FRAMES ships Wikipedia links, not text, and a live page changes every week, so the article
text comes from a snapshot we built and published once. Its card says how it was built, what
the text keeps (body, headings, tables and infoboxes as `| a | b |` rows) and what it lacks
(values today's templates computed after 2024, and templates deleted since). The loader joins
the two by row index and refuses a row whose prompt the snapshot was not built for.

**822 Cases, not 824.** Two questions are left out by name on the row (`excluded_sample_ids`),
because their own articles cannot answer them: question 141's only source, "Nemanja Marković",
was deleted from Wikipedia before it could be frozen, and question 77's answer sits in a table
that only a template deleted since 2024 drew. Question 540 keeps 19 of its 20 articles; the
missing one, "Jack Vance (tennis)", is not needed for its answer.

## The prompt

One user message: each article as `=== Article N: Title ===` and its text, in the question's
link order, then `Question: ` and the question. The paper publishes no oracle template, so the
wording is ours. Prompts run long (median about 78,000 characters, the longest about 727,000),
and a prompt longer than a Candidate's context window fails that one Case.

## Scoring

The paper's auto-rater (Figure 6), word for word as its LaTeX source writes it, sent to the
house Judge: the system message `You are a helpful assistant.` and the rating prompt with the
question, the Candidate's whole reply and the gold answer. The Judge never sees the articles.
`Decision: TRUE` scores 1.0 and `FALSE` 0.0; the headline is the mean, plain accuracy. A reply
with no decision is asked again twice, then the Case fails as `judge_reply_invalid` and leaves
Coverage. The paper graded with Gemini-Pro-1.5; we grade with the house Judge every judged
Benchmark here pins, so our numbers sit beside the paper's rather than on its exact scale.

## Baselines

- The paper's Oracle score: 0.729 (Gemini-Pro-1.5), 0.665 (Gemini-Flash-1.5).
- No human baseline is published.

## Identity

The Benchmark revision hashes the Case Digest, the Task reference, both Hub pins and the
sha256 of every `.py` file in this package (`task_source=…`). Editing `frames.py` (the prompt,
the judge text, the decision reader) is a new Benchmark: update the literal in
`tests/unit/inspect/test_published_revisions.py` and say why in the PR.

## Running it locally

```sh
# import (two clean-room replays + the two rows; already done, re-run only to re-seal)
HF_HUB_DISABLE_XET=1 uv run python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.frames.frames:frames_oracle --key frames_oracle \
    --keep-sample-metadata --excluded-sample-id 77 --excluded-sample-id 141
# prepare the bundle
uv run python -m screamingface_engine.benchmarks.prepare --root /tmp/assets --bundle frames_oracle
```

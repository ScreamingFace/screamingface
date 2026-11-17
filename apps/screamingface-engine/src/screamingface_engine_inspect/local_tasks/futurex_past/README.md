# FutureX-Past

[FutureX: An Advanced Live Benchmark for LLM Agents in Future Prediction](https://arxiv.org/abs/2508.11987)
(Zeng et al., 2025) is a live benchmark: every week it asks agents about events that have not yet
happened. **FutureX-Past** ([`futurex-ai/Futurex-Past`](https://huggingface.co/datasets/futurex-ai/Futurex-Past),
Apache-2.0) is its archive of questions whose outcomes are now known: sports results, rankings,
prices, releases, in English and Chinese.

This package holds two **local Tasks** over one loader (spec
`docs/spec/2026-11-16-futurex-past-local-task.md`):

| Benchmark | Data | Marking | Use it for |
|---|---|---|---|
| `futurex_past` | commit `8299bfa1`, 2,036 questions | the FutureX authors' current scorer, with our house Judge on levels 3-4 | a score on the FutureX authors' scale |
| `futurex_past_study` | commit `3c2e3969`, 1,118 questions | the crowd-wisdom study's code, no Judge | replicating that study's numbers |

**Read a score with this in mind.** The events have already happened, and the Candidate gets no
search. A model trained after an event may simply know its outcome. The dataset card itself says
FutureX-Past should not be used to evaluate live prediction. A score here measures closed-book
answering on resolved events. It is not comparable with the live FutureX leaderboard, whose agents
search the web before the event.

## Dataset

The parquet `data/train-00000-of-00001.parquet` at a pinned commit, sha256-checked before it is
read. The dataset is re-published weekly, which is why both Benchmarks pin a commit.

- **Case id**: `<id>|<end_time>`. The dataset reuses an `id` when a question recurs on another
  date: 21 ids cover 119 rows at `8299bfa1`. This pair is unique, and it is the crowd-wisdom
  study's own `item_id`.
- **Levels**: 1 = pick one of a few options, 2 = pick every right option, 3-4 = an open answer
  (a number, a name, or a list).
- **One data defect**: one key is the bare string `[Yes]`, which is not a Python literal. We read
  it as `["Yes"]` (named deviation); the authors' scorer keeps it as a label nothing can match.

## The prompt

The row's `prompt`, byte for byte, as one user message. FutureX ships a complete prompt that ends
with its own answer format (`\boxed{...}`), so nothing is added.

## Reading the reply

The answer is the content of the **last** `\boxed{...}` in the reply, with one level of nested
braces allowed. In `futurex_past`, a `\text{...}` wrapper around the whole box is removed, the
content is split on commas, and a `\text{...}` around a single item is removed too
(`\text{A}, \text{B}` reads as A and B); a reply with no box has no answer and scores 0. In
`futurex_past_study`, the study's own reader is used (see below), and a reply with no usable
answer leaves the score.

## Scoring: `futurex_past`

The reference is the authors' scorer, [Futurex-Eval@2626f7a2](https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5).
It publishes **no licence**, so `grading.py` re-implements its rules, and our judge prompts ask
the same questions in our own words. No Futurex-Eval code is copied. Each rule's docstring names
the upstream function.

| Level | Rule | Upstream |
|---|---|---|
| 1-2 | Labels normalised (quotes, wrappers, a lone letter upper-cased, Yes/No). One key: the prediction list must equal it. Several keys: set F1. | `eval.py` `estimate_score_level_1_2` |
| 3-4, routing | The Judge decides, once per Case in each grading run, whether the answer is option labels, a number/text/ranking, or an unordered set. A Yes/No prompt whose key is not Yes/No skips the router. An unreadable route falls back to number/text/ranking. | `metric_router.py` `route_metric` |
| 3-4, one number | A whole plain number is read by rule (LaTeX's `{,}` thousands separator read as a comma); prose goes to the Judge, which extracts the number from its first comma piece. Score = max(0, 1 − ((ŷ − y)/σ)²), σ = 5% of the key, 0.01 for a zero key; a non-finite prediction scores 0. | `eval.py` `estimate_score_level_3_4`, `llm_judge_level_34.py` |
| 3-4, one name | The Judge says whether the first comma piece of the answer matches the key, ignoring language and wording. | `judge_str_match` |
| 3-4, a ranking | Option letters in any order → 1. The Judge's position-by-position Yes → 1. Otherwise 0.8 × the Judge's overlap count / k. | `judge_rank_overall` |
| 3-4, an unordered set | The same set, case-folded → 1. Otherwise the Judge counts one-to-one matches m: 1 when m = k = \|prediction\|, else 0.8 × m / k. | `judge_unordered_set_overall` |

**Headline**: the paper's overall score, the four level means weighted 10/20/30/40
(`run_weekly_leaderboard.py`), honoured as the whole-run metric. Each Case's Score metadata
carries its `level` and `route`, so a run can be cut per level.

**The Judge** is the house judge, `openrouter/openai/gpt-5.4`, at temperature 0. It is asked
through the shared redraw loop.

### Named deviations

- The Judge model: upstream uses DeepSeek V4 Flash or GPT-4.1.
- Reading the reply: upstream asks an LLM to extract the answer from the whole reply, so a
  boxless reply can score there. Here the box is read by rule, and a box that is a whole plain
  number (`$115`, `115%`, `6,923.23`, `1e3`) is read by rule instead of asking whether it is a
  number. Anything else, such as `1/2` or `10^3`, goes to the Judge. Upstream's own `to_float`
  would read only the first numeric run, but it only sees text its extractor has already
  rewritten as a number.
- `[Yes]` is read as `["Yes"]`.
- Only a `\boxed{}` or `\text{}` wrapper is removed from a label; `\boxed{\textbf{A}}` does not
  read as `A`. Upstream's LLM extractor would read it.
- An unreadable judge reply (no count, no extracted number) is redrawn twice, then fails the Case
  as `judge_reply_invalid`. Upstream scores it 0. Under `coverage_declare` such a Case leaves the
  headline's denominator (it shows in Coverage) instead of counting 0. The router keeps
  upstream's fallback, after three asks where upstream makes two.
- The Judge's token cap is 4,096 for every question. Upstream allows 5,000 for its judges and 512
  for the router and the set count.
- A rank overlap count is capped at k, so a Case stays in [0, 1]. Upstream does not cap it.
- A level missing from a run renormalises the weights. Upstream counts it as 0. The two agree on
  every full run.
- The router decision is not cached across runs, as upstream caches it; each run routes again at
  temperature 0.
- Failure policy `coverage_declare`: a Case whose Candidate call failed leaves the score and is
  reported in Coverage. The paper excludes a missing prediction too (§3.4.2), although upstream's
  weekly script counts it as 0. The Engine allows no other policy with a whole-run metric yet
  (OME-1642).
- A Case whose Candidate abstained and whose grading then failed reaches the headline as a bare 0
  with no level (`single_shot._metric_sample`). It cannot be placed in a level, so it is left out
  of the headline; its Case Result shows 0. Upstream counts a scoring failure as 0 in its level.
  The two agree on every run where no abstained Case fails grading.

### Upstream notes

- The paper (§3.4.3) sets σ as the outcome's standard deviation over the past 7 days, and the
  dataset has a `std` column filled on 238 rows. The authors' code ignores both and uses 5% of
  the key. We follow the code; `std` stays in the metadata.
- The paper scores level 2 by F1, while its tier description says a missed option halves the
  score and a wrong one zeroes it. The code uses F1, and so do we.
- A match, and the rank judge's position-by-position verdict, is read as "the word yes anywhere
  in the judge's reply" (`'yes' in ans.lower()`), so a reply that writes "yes" while comparing
  positions and ends `\boxed{No}` reads as a match. We copy this, because it is how upstream
  marks; with another judge model it can inflate scores differently.
- Upstream's own test `test_contract_conflict_skips_router` fails at the pinned commit: level 1-2
  questions are routed by rule before the conflict check. No level-3/4 question here has a
  conflict.

## Scoring: `futurex_past_study`

The crowd-wisdom study ("behavior-aware LLM crowds for future prediction") marked FutureX-Past
with its own deterministic code. Two of its files are copied byte for byte below our header:
`vendor/study_metrics.py` is its `committee_kit/metrics.py` (the scores), and
`vendor/study_formats.py` is its `1_forecasting_prompts/bench_formats.py` (the reply reader and
the interpretability gate). Its author contributes both under this repository's Apache-2.0
licence, and `test_local_task_futurex_past_study.py` pins each sha256.

- The reply is read with the study's `futurex_parse` (the last box, no unwrapping) and split on
  commas.
- **A reply with no usable answer leaves the score**, as the study's `rank.score_entry` drops such
  a cell from both sides of the fraction. That covers no answer in the box, and a box the study's
  `interpret_answer` rejects against the question's own prompt (a hedge such as `maybe`, every
  option selected, an option the question does not offer). Its Score shows
  `study_usable: false` and the reason, and its per-Case value is still the study's mark of
  its tokens (so the per-Case mean includes it; only the headline leaves it out). A Candidate
  call that failed leaves it too (`coverage_declare`).
- Both sides are case-folded and whitespace-collapsed (the study's `corpus.normalise`).
- Level 1: the list must equal the key. Level 2: set F1. Levels 3-4: 1 for an exact ordered
  match, else 0.8 × overlap / k. Names and numbers compare as text, with no Judge and no σ, so this
  Benchmark scores below `futurex_past` on levels 3-4 by design.
- Headline: the study's `tier_weighted`, which applies the 10/20/30/40 weights over the levels
  present.

**Replication.** Commit `3c2e3969` (2026-08-02) is the latest release holding all 100 of the
study's questions, with the study's exact keys; a later release removed one. The study's
questions are these Case positions (1-based, file order), to pass as `cases=[...]`:

```
172, 182, 188, 189, 202, 212, 234, 242, 261, 266, 273, 276, 284, 289, 291, 293, 297, 311, 338, 341,
365, 378, 386, 397, 401, 403, 427, 431, 438, 439, 454, 468, 494, 501, 507, 515, 518, 527, 543, 560,
578, 600, 603, 609, 615, 622, 630, 663, 664, 707, 713, 731, 738, 749, 759, 762, 763, 764, 783, 785,
789, 794, 799, 810, 812, 814, 826, 834, 836, 839, 847, 852, 878, 887, 896, 906, 909, 923, 957, 959,
971, 976, 979, 989, 991, 993, 1006, 1013, 1021, 1035, 1040, 1045, 1056, 1058, 1065, 1068, 1070,
1075, 1107, 1114
```

`test_local_task_futurex_past_study.py` feeds the study's stored answers through this scorer and
reproduces the study's reported score of all 27 models and of the fused-medoids committee
(**0.302**, Table III of the study), with every exclusion the study made (23 no-answer and 15
uninterpretable cells). It matches to 1e-12: Python 3.11 and 3.12 round `statistics.fmean`'s last
bit differently, and the study's kit gives our exact values under 3.12. The fixtures were generated
from the study package by `tests/fixtures/futurex_past_study/make_replication_fixture.py`.

**To replicate a run, sample as the study did.** The study called every model at temperature 0
and, when a reply was cut off, called again with a larger token cap. The Benchmark does not set
the Candidate's sampling. Pass `temperature: 0` in the Candidate's params where the provider
accepts it, and leave room in `max_tokens`.

**A committee tie is a Candidate-side difference.** The study scored a committee with no majority
0 and kept it in the score (its fused-medoids committee tied on 2 of the 100 questions). A
ScreamingFace fusion answers on a tie (the contributor's fusions keep the first member's answer),
so on those questions it is marked on a real answer: the headline can differ from the study's by
up to +0.0071 (2 level-1 Cases). Grading is the study's either way; this is what the Candidate
writes.

## Baselines

- Human: not published.
- Frontier: not published for this archive. The paper and the leaderboard score agents with
  search on the live weekly questions.

## Draft Feedback

Off for both Benchmarks: feedback on a forecast would leak the outcome.

## Identity

The fingerprint hashes the Case Digest, the Task reference, the Hub pin, the judge, and the
sha256 of every `.py` file in this package (`task_source=…`). Editing any of them moves only the
fingerprint. Whether the published revision moves too is the owner's call, under
[Changing a Benchmark's published revision](../../../../docs/adding-an-imported-benchmark.md#changing-a-benchmarks-published-revision).

## Running it locally

```sh
uv run python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.futurex_past.futurex_past:futurex_past \
    --key futurex_past --whole-run-metric honour
uv run python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.futurex_past.futurex_past_study:futurex_past_study \
    --key futurex_past_study --whole-run-metric honour
```

The example notebook is `packages/screamingface/examples/21_futurex_past.ipynb`.

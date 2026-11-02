# BIG-Bench Hard, asked and marked the paper's way

[Challenging BIG-Bench Tasks and Whether Chain-of-Thought Can Solve Them](https://arxiv.org/abs/2210.09261)
(Suzgun et al., 2022). 23 reasoning tasks where language models trailed average human raters,
27 subsets (logical deduction and tracking shuffled objects come in three sizes each), 6,508
Cases.

This is a **local Task** (OME-1696) built from
[inspect_evals' `bbh`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/bbh).
It reuses inspect_evals' loader, its 3-shot chain-of-thought examples and its dataset pin, so the
questions are inspect_evals' own. Three things differ.

## Why a local Task

inspect_evals tags each question with the kind of answer it expects as a Python enum. Case
Preparation seals Sample metadata as JSON, so the importer refuses inspect_evals' Task. Here the
tag is the enum's name, a string.

## Where we follow the paper, not inspect_evals

| | inspect_evals | this Benchmark | why |
| -- | -- | -- | -- |
| Multiple-choice instruction (17 subsets, 4,071 Cases) | "The entire content of your response should be … 'ANSWER: $LETTER'", above worked examples that reason step by step | inspect's `multiple_choice(cot=True)`: "Think step by step before answering", answer on the last line | the paper's headline setting is chain of thought; the answer-only instruction contradicts the examples |
| Free-form grading (Dyck languages, multistep arithmetic, object counting, word sorting; 1,000 Cases) | `match(location="end")`: lowercase, trim punctuation off both ends, then "does the reply end with the key?" | exact match on the final answer (after the last `ANSWER:`, else the paper's "the answer is"; either label in any case), with spaces, `**` and backticks trimmed and one trailing period dropped | the paper grades by exact match (§3, "Evaluation protocol") |

What inspect_evals' free-form grading marks correct:

- Dyck languages: the key `ANSWER: ] ]` trims to `answer`, so any reply ending on an `ANSWER:` line of
  brackets is right, a bracket missing (`ANSWER: ]`) or extra (`ANSWER: ] ] ]`), and so is "I do not
  know the answer.".
- multistep arithmetic: `ANSWER: 25` for the key `-25`, and `ANSWER: 125` for `25`.
- object counting: `ANSWER: 12` for the key `2`.
- word sorting: `ANSWER: elizabeth kenya`, or any extra word in front, for the key `beth kenya`.

The evidence: the authors publish no grading code, but
[their repository](https://github.com/suzgunmirac/BIG-Bench-Hard/tree/9ee07bd481feebf959a6b59d61ea57bdcf30964d)
ships Codex's replies with their accuracy per subset. Our rule reproduces all four of those
numbers (Dyck 56.8, multistep 47.6, object counting 93.2, word sorting 40.4).
`tests/unit/inspect/test_local_task_bbh.py` pins this on those replies, kept in
`tests/unit/data/bbh_codex_cot_free_form_replies.json` (MIT).

Unchanged from inspect_evals: the multiple-choice subsets grade the chosen letter (`choice()`),
the 6 yes/no-style subsets the word after `ANSWER:` (`answer(pattern="word")`). No judge.

## Score

Plain accuracy over the Cases run, inspect's overall figure. The paper's headline is the
unweighted mean over the 23 tasks; on the authors' Codex replies the two differ by under 0.1
point (73.97 against 73.9). Each Case keeps its subset name, so both can be regrouped.

## Dataset

`Joschka/big_bench_hard` at commit `76eaa8c2`, MIT. Its targets and options match the authors'
`bbh/` files on all 6,511 questions. One question is left out by id
(`movie_recommendation_164`): the authors' data splits its answer "Monsters, Inc" into two
options, so no reply can be right. The paper counts it, always wrong. inspect_evals already drops
two `ruin_names` questions broken the same way.

## Identity

The fingerprint hashes everything that defines this Benchmark, the sha256 of every `.py` file in
this package included (`task_source=…`). Editing any of it moves only the fingerprint: `tests/unit/inspect/test_benchmark_fingerprints.py`
goes red and the Benchmark keeps publishing its hand-set `published_revision` (OME-1610).
Whether that id moves too is the owner's call, under [Changing a Benchmark's published revision](../../../../docs/adding-an-imported-benchmark.md#changing-a-benchmarks-published-revision).

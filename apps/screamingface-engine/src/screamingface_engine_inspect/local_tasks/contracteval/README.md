# ContractEval

[ContractEval: Benchmarking LLMs for Clause-Level Legal Risk Identification in Commercial
Contracts](https://arxiv.org/abs/2508.03080) (Liu et al., 2025). 4,182 (contract, clause
category) pairs from the CUAD **test** split: 102 real commercial contracts × 41 clause
categories. The model gets a full contract and one category, and must quote the answering
sentences verbatim or reply `No related clause.`

This is a **local Task** (OME-1527): the hand-built `benchmarks/contracteval/` folder rewritten
in inspect's shape (dataset loader, scorer, whole-run metric, one `@task`) and fed to the same
importer that imports inspect_evals. The Benchmark keeps its id, `contracteval`, and is ours
(`origin="screamingface"`).

## Dataset

`theatticusproject/cuad-qa`, split `test`, at commit `d9c4ee02` of the Hub's auto-converted
parquet branch (CUAD's `main` holds only a loading script, which `datasets` 4.x no longer runs).
CC BY 4.0. 1,244 rows have gold clause sentences; 2,938 (70.3%) have none, and their answer
key is `[]` (the row's `empty_answer_key_allowed`).

## The prompt

One user message: the reference harness's system prompt, a newline, then its user template
with the contract and the category (`proprietary_model.py` at `f2de7447`, MIT). The bytes equal
the hand-built Benchmark's for all 4,182 Cases, including one known delta from the reference:
`Context:` without the reference's trailing space. A system message would change the bytes,
because capture joins it with a blank line where the reference uses one newline.

## Scoring

`grading.py` reproduces the reference's rules (cited, not vendored; `tests/unit/
_contracteval_reference.py` is the verbatim copy and `test_contracteval_parity.py` proves the
two agree on real CUAD gold spans):

- a Case with gold sentences is correct only when **every** one appears in the reply (after
  stripping spaces, newlines and backticks); no partial credit;
- a Case with none is correct only when the reply contains "no related clause", case-folded.

The headline is **F1 over the run's confusion matrix** (`contracteval_f1`, honoured through the
row's `whole_run_metric`), not the mean of Case scores: a model that always declines is right
on 70% of Cases and scores F1 0. One named deviation: where the reference divides by zero
(no true positive), F1 is 0.0.

Each Case's Check carries `is_positive`, `abstained` and `jaccard` (token overlap with the gold
text). The hand-built Benchmark also published run-level precision, recall, F2, accuracy,
the abstention and false-abstention ("laziness") rates and the mean Jaccard over clause rows;
the lane publishes only the headline (a whole-run metric returning several numbers is
refused), so those are not served. Accuracy is `correct / scored_cases` from the run metrics.

## Identity

The revision hashes the Case Digest, the Task reference, the Hub pin, the whole-run metric and
the sha256 of every `.py` file in this package (`task_source=…`). Editing `contracteval.py` or
`grading.py` is a new Benchmark: update the literal in
`tests/unit/inspect/test_published_revisions.py` and say why in the PR.

## Running it locally

```sh
# import (two clean-room replays + the two rows; already done — re-run only to re-seal)
uv run python -m screamingface_engine_inspect.importer \
    screamingface_engine_inspect.local_tasks.contracteval.contracteval:contracteval \
    --key contracteval --empty-answer-key-allowed --whole-run-metric honour
# prepare the bundle
uv run python -m screamingface_engine.benchmarks.prepare --root /tmp/assets --bundle contracteval
```

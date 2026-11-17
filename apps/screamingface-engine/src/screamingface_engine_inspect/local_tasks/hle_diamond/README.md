# HLE-Diamond, asked and judged as inspect_evals' hle

[HLE-Diamond](https://lastexam.ai/blog/hle-diamond) is the cleaned successor to
[Humanity's Last Exam](https://arxiv.org/abs/2501.14249) (Phan et al., 2025), released by the
[Center for AI Safety](https://www.safe.ai/) and [Scale AI](https://scale.com/) on 22 September
2026. It has 1,000 expert-written questions, 500 marked reasoning and 500 marked knowledge.
272 of them come with one picture.

This is a **local Task** (OME-1863) around
[inspect_evals' `hle`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/hle).
It reuses inspect_evals' system prompt, its `record_to_sample`, its `regex_judge` scorer spec,
its generation settings and its epoch reducer, all imported at the pinned `inspect-evals`
version. Only the dataset differs.

## Why a local Task

inspect_evals' `hle` Task can load only `cais/hle` or `cais/hle-rolling`. HLE-Diamond is a
separate Hub dataset, so this Task points the same exam at it.

## Why not filter the `hle` Benchmark

`hle` cannot stand in for HLE-Diamond. Counted at the two pinned revisions:

| | Cases |
| -- | -- |
| Diamond questions not in `hle` | 397 |
| shared questions with a corrected answer | 80 of 603 |
| shared questions with reworded text | 124 of 603 |

A filtered `hle` run would miss 397 questions and grade 80 against answers the authors
corrected.

## What is ours

Two things, both marked `OURS` in the module.

- Each Case keeps the row's `partition` (`reasoning` or `knowledge`) in its Sample metadata.
  That metadata is private Grading Material, never shown to the Candidate, and nothing reads it
  today. It is inside the Case Digest, so keeping it now means a per-half score can be added
  later without changing the Cases.
- The Task leaves out inspect_evals' `version=` and `metadata=` labels, which name inspect_evals'
  own Sample set, not this one. Neither is part of any Case.

## Asking and scoring

Exactly as the `hle` Benchmark: inspect_evals' `system_mc` system prompt asks for an
explanation, an answer and a confidence. It reaches the Candidate as user text ahead of the
question, not as a system turn (the plugin's Named Deviation, as on `hle`). The judge,
glm-5.3-flash through our gateway, grades the final answer with inspect_evals' `regex_judge`
prompt, up to three tries. The headline is the mean of correct/incorrect over the Cases run (a
reply the judge cannot grade counts wrong, the CAIS leaderboard's accounting). The Candidate's stated confidence is published beside it.
No per-half score is published (owner decision, 2026-11-16).

## Dataset

[`cais/hle-diamond`](https://huggingface.co/datasets/cais/hle-diamond) at commit `04eeb7ef`,
test split. Gated: the import and every build need a Hub login token (`HF_TOKEN`). The columns
are `cais/hle`'s plus `partition`.

## Licence

MIT, the dataset card's header at the pinned revision. The card also asks users not to publicly
share, re-upload or distribute the questions. The frozen Cases ride inside the benchmark image,
as `hle`'s do (owner decision, 2026-11-16).

## Identity

The fingerprint hashes everything that defines this Benchmark, the sha256 of every `.py` file in
this package included (`task_source=…`). Editing any of it moves only the fingerprint: `tests/unit/inspect/test_benchmark_fingerprints.py`
goes red and the Benchmark keeps publishing its hand-set `published_revision` (OME-1610).
Whether that id moves too is the owner's call, under [Changing a Benchmark's published revision](../../../../docs/adding-an-imported-benchmark.md#changing-a-benchmarks-published-revision).

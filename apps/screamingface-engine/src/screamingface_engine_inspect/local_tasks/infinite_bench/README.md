# InfiniteBench Math.Find, cut once for every model

[∞Bench: Extending Long Context Evaluation Beyond 100K Tokens](https://arxiv.org/abs/2402.13718)
(Zhang et al., 2024). Math.Find gives the model a list of tens of thousands of numbers and asks
for one of seven: the largest three, the smallest three, or the median. 350 Cases.

This is a **local Task** (OME-1602) built from inspect_evals' `infinite_bench_math_find`. It
reuses upstream's loader, system message and prompt template, so the questions are upstream's
own. One piece is swapped: the input cut.

## Why a local Task

Upstream's Task cuts each long input to the answering model's context window, and to know the
window it asks which model is answering (`get_model()`). Task replay seals the Cases with no
model at all, and the importer refuses a Task whose Cases depend on the model's name: the
Cases it sealed would be cut for a model that doesn't exist.

Here the cut is fixed: upstream's own character cut, at the budget upstream gives every model
outside its context table (128k tokens, about 446,250 characters). Every Candidate gets the
same Cases.

## What that changes

Nothing, today. The longest Math.Find input is 120,155 characters (mean 118,028), so no input
reaches the cut and every Case is upstream's whole input. The fixed cut keeps that true
whoever answers.

## Scoring

inspect's own `exact()` against the single answer, as upstream grades. No judge. Benchmark
score is plain accuracy over the Cases run.

## Dataset

`xinrongzhang2022/InfiniteBench` at commit `90f03943`, file `math_find.jsonl`. The card's
licence line reads apache-2.0; its header is malformed, so the Hub shows no licence (owner
decision on OME-1602, 2026-10-14). The other 8 InfiniteBench tasks stay parked for their cost.

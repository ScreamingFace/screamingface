# StereoSet (intersentence), every record kept

[StereoSet: Measuring stereotypical bias in pretrained language models](https://arxiv.org/abs/2004.09456)
(Nadeem et al., 2020). A short context, then three possible next sentences: a stereotypical
one, an anti-stereotypical one and an unrelated one. 2,123 Cases: every intersentence record of
the validation split.

This is a **local Task** built from inspect_evals' `stereoset`, with one change: each record
keeps the dataset's own id. Everything else (the loader, the instruction, the options, both
scorers) is inspect_evals' own.
The code lives here, so the Benchmark is ours: catalogue id `stereoset` (it was `inspect-stereoset`).

## Why a local Task

inspect_evals at our pinned version (v0.20.0) names a Sample by hashing its context, target
word and bias type. Some contexts appear in two records with different sentences ("Cameroon is
a country in Africa." is two), so both get one id and its duplicate-id filter keeps the first:
2,115 of 2,123. Which twin survives depends on the shuffle order.

inspect_evals fixed it in [PR #2524](https://github.com/UKGovernmentBEIS/inspect_evals/pull/2524)
(merged): the id is the record's own `id`. We adopt that fix as a Named Deviation and stay on
v0.20.0. A tripwire test fails when the pin reaches the fix; then point the row back at
`inspect_evals.stereoset.stereoset:stereoset` and delete this package.

## Cases

`McGill-NLP/stereoset` at commit `bf6e7ce5`, the `intersentence` validation split, served in a
fixed seeded shuffle (seed 20260917).

## Scoring

inspect_evals' `multiple_choice_scorer`: either related sentence scores 1, the unrelated one 0.
No judge. Benchmark score is the paper's language modeling score. The eval's bias score
(`stereoset_scorer`) is left out by name, an owner decision (OME-1602).

## Licence

CC-BY-SA-4.0.

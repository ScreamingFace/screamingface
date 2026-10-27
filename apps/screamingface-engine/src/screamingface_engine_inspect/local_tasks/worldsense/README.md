# WorldSense, every trial kept

[WorldSense: A Synthetic Benchmark for Grounded Reasoning in Large Language Models](https://arxiv.org/abs/2311.15930)
(Benchekroun et al., 2023). Questions about small described worlds (orderings and spatial
relations). 87,048 Cases: every trial of the test set.

This is a **local Task** built from inspect_evals' `worldsense`, with one change: each trial
keeps its own id. Everything else (the loader, the questions, the pattern scorer, its
metrics) is inspect_evals' own.
The code lives here, so the Benchmark is ours: catalogue id `worldsense` (it was `inspect-worldsense`).

## Why a local Task

WorldSense asks several questions (trials) about one described world (a tuple), arranged so
each possible answer is right exactly once per tuple. That balance is how the paper cancels a
model that always says "TRUE".

inspect_evals at our pinned version (v0.20.0) names a Sample after its tuple, so every trial
of a tuple gets the same id, and its duplicate-id filter keeps the first: 40,176 of the 87,048
trials, every one of them the "yes" side. No Case had the answer FALSE, IMPOSSIBLE or "2", and
answering TRUE, POSSIBLE or "1" to everything scored 0.917.

inspect_evals fixed it in [PR #2507](https://github.com/UKGovernmentBEIS/inspect_evals/pull/2507)
(merged): the id is the trial's own `Key`. We adopt that fix as a Named Deviation and stay on
v0.20.0. A tripwire test fails when the pin reaches the fix; then point the row back at
`inspect_evals.worldsense.worldsense:worldsense` and delete this package.

## Cases

`facebookresearch/worldsense` at commit `bd81d945`, `data/worldsense/test_set/trials.jsonl.bz2`,
sha256 `00c94031…` (inspect_evals' own pins). Per family, each answer is right equally often:
Infer TRUE/FALSE, Consist POSSIBLE/IMPOSSIBLE, Compl "1"/"2"/"3".

## Scoring

inspect_evals' `pattern_with_metadata`: the leading 1/2/3/TRUE/FALSE/POSSIBLE/IMPOSSIBLE of the
reply against the key. No judge. Benchmark score is plain accuracy over the Cases run, not the
paper's bias-corrected accuracy (which the eval reports as `ws_accuracy`).

## Licence

CC-BY-NC-4.0 (facebookresearch/worldsense LICENSE): non-commercial use only.

## Identity

The fingerprint hashes everything that defines this Benchmark, the sha256 of every `.py` file in
this package included (`task_source=…`). Editing any of it moves only the fingerprint: `tests/unit/inspect/test_benchmark_fingerprints.py`
goes red and the Benchmark keeps publishing its hand-set `published_revision` (OME-1610).
Whether that id moves too is the owner's call, under [Changing a Benchmark's published revision](../../../../docs/adding-an-imported-benchmark.md#changing-a-benchmarks-published-revision).

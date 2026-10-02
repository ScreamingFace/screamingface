---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-02
---

# OME-1273 — the four upstream issue drafts, re-checked against inspect_evals 0.20.0

OME-1273's table parks four packages as "upstream issue: a bug in inspect_evals 0.20.0. We
draft the issue here, the owner posts it". Before drafting, each was re-checked by calling
the eval's own task function the way inspect does, with a real fetch and no model
(`inspect-evals` 0.20.0, `inspect-ai` 0.3.263, the versions `uv.lock` pins; 2026-10-02).
The earlier evidence came from the 116-task sweep in PR #1018, whose Hugging Face reader fed
every eval a stand-in `Sample` (no `id`, no `metadata`); three of the four crashes were that
stand-in's, not the eval's. Result: **one draft, three "does not reproduce"**. The owner posts
the one draft; nothing here was posted.

| Package | Sweep verdict (PR #1018) | Re-check against 0.20.0 | Outcome |
| -- | -- | -- | -- |
| bbh | `TypeError: unsupported format string passed to NoneType.__format__` at `bbh.py:136` | builds: 6,509 Samples, first id `date_understanding_001` | does not reproduce |
| personality (TRAIT) | `ValueError: Missing choice_scores metadata for TRAIT sample.` at `personality.py:269` | cannot be checked: `mirlab/TRAIT` is a gated dataset | not reproducible here |
| sciknoweval | `TypeError: 'NoneType' object is not subscriptable` at `sciknoweval.py:147` | builds: 66,386 Samples with `task`/`subtask`/`domain` metadata | does not reproduce |
| novelty_bench | `ModuleNotFoundError: No module named 'torch'` at `novelty_bench.py:88` | reproduces, same line | **drafted below** |

## bbh — does not reproduce

Calling `inspect_evals.bbh.bbh:bbh()` with a real fetch builds a Task of 6,509 Samples. The
sweep's crash came from the importer's own stand-in Sample: `sample.id` was `None` there,
so `f"{subset_name}_{sample.id:03d}"` (`bbh.py:136`) could not format it. With
`hf_dataset(auto_id=True)` (`bbh.py:121`) every real Sample has an integer id, and the line
works. No issue to post.

One observation, not the ticket's bug and not drafted: the four converters set
`id=create_stable_id(record["question"], prefix="bbh")` (`bbh.py:333`, `:348`, `:361`,
`:374`), and `auto_id=True` then replaces every one of them with a running number, so the
stable ids never reach a Sample. Harmless at 0.20.0; worth one line upstream only if the
owner wants to raise it.

## personality_TRAIT — not reproducible here

`personality_TRAIT()` fetches `mirlab/TRAIT`, a gated Hugging Face dataset
(`DatasetNotFoundError: Dataset 'mirlab/TRAIT' is a gated dataset on the Hub`), so the task
cannot be built without an access grant. The sweep's `Missing choice_scores metadata` was
raised at `personality.py:269` on the importer's stand-in Sample, whose `metadata` was
`None`; the real records carry `choice_scores` by the eval's own `record_to_sample`
(`personality.py:244-255`). No draft: there is nothing to report until someone with access
re-runs it, and the expected outcome is that it builds.

## sciknoweval — does not reproduce

`sciknoweval()` builds a Task of 66,386 Samples; every Sample carries the `domain`, `level`,
`task`, `subtask` and `type` metadata its filter reads (`sciknoweval.py:147`). The sweep's
`'NoneType' object is not subscriptable` was the stand-in Sample's `metadata=None`. No
issue to post.

## novelty_bench — reproduces; draft for the owner to post

**Title:** `novelty_bench` imports torch while the Task is built, so the task cannot even be
constructed without it, and no extra installs it

**Minimal repro (inspect-evals 0.20.0, inspect-ai 0.3.263, Python 3.12, torch not
installed):**

```python
from inspect_evals.novelty_bench.novelty_bench import novelty_bench
novelty_bench()
```

**Expected:** the Task is built (its dataset is a plain `hf_dataset` call); torch is needed
only when the scorer loads the partition classifier and the reward model, so the import
could wait until scoring, or `uv sync --extra novelty_bench` could install it first.

**Actual:**

```text
  File ".../inspect_evals/novelty_bench/novelty_bench.py", line 88, in novelty_bench
    quality_model_device=select_device(quality_model_device),
  File ".../inspect_evals/novelty_bench/utils.py", line 26, in select_device
    import torch
ModuleNotFoundError: No module named 'torch'
```

**Where:** `src/inspect_evals/novelty_bench/novelty_bench.py#L88` calls
`select_device(...)` for both scorer models inside the `@task` function;
`src/inspect_evals/novelty_bench/utils.py#L26` does `import torch` at the top of
`select_device`. The eval is marked `isolated: true` in its `eval.yaml`, but the 0.20.0 wheel
declares no `novelty_bench` extra (`Provides-Extra` lists `personality`, `sciknoweval`, … and
not this one), so there is no `inspect_evals[novelty_bench]` to install either.

**Suggested fix (either):** resolve the devices lazily inside `novelty_bench_scorer` (or
inside the model loaders), so building or listing the Task needs no torch; or declare the
extra the `isolated` flag implies, so the failure names the install step. Happy to open a PR
for the lazy import if that is the preferred shape.

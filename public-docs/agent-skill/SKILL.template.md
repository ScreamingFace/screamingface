---
name: screamingface
description: Use when writing, running or debugging Python code that imports `screamingface` (`import screamingface as sf`). Covers composing fusions with `sf.Fanout`, `sf.Synthesize` and the reducers, evaluating them on a benchmark, connecting providers, reading reports and costs, and sharing a run as a url4. Generated from the ScreamingFace Client docs, version {{version}}.
---

# ScreamingFace Client

`screamingface` is the Python library of the ScreamingFace Client. You compose models into a fusion, evaluate it on a benchmark, and read the score and the cost.

Docs version: {{version}}. This skill is generated from https://docs.screamingface.ai. Each docs page is one Markdown file in `references/`, and the index below lists them all.

## Before you write code

- Python 3.12 or newer. In a notebook, `!pip install "screamingface[notebook]"`. From a terminal, `uv pip install "screamingface[notebook]"`. The `[runtime]` extra adds the local engine. See [Installation](references/sf-client-installation.md).
- The Client never calls a model provider itself. It needs an engine: a hosted one (access is granted by the OpenMined team) or one on your own machine, started with `screamingface up`, which uses your own provider keys.
- A local engine started with `screamingface up` serves one benchmark, `medxpert`. The hosted engine serves the others.
- On a hosted engine, log in with `client.login()` on a `sf.Client(engine_url=...)`. See [Installation](references/sf-client-installation.md) and [Connections](references/sf-client-guides-connections.md).

## Rules

1. Build a fusion as a chain: `sf.Fanout([model_a, model_b]) >> sf.Synthesize("provider/model")`. A reducer such as `sf.Vote()` can end the block in place of `sf.Synthesize`. See [Fusions](references/sf-client-guides-fusions.md) and [Reducers](references/sf-client-api-reducers.md).
2. Pass `benchmark=` to every `sf.evaluate` call. It has no default. Use `limit=` while you iterate: it caps the case count and is the main cost control. See [Running an evaluation](references/sf-client-guides-running-an-evaluation.md).
3. A run is paid on your own provider keys when you use a local engine. Read the cost from `report.usage.cost_usd`. See [Usage](references/sf-client-api-usage.md).
4. Use only names in `sf.__all__`. [The sf namespace](references/sf-client-api-modules.md) lists the modules and the references list every public name.
5. Read an error by its code. [Errors](references/sf-client-api-errors.md) lists the classes and the codes.

## Index

{{index}}

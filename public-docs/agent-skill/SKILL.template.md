---
name: screamingface
description: Use when writing, running or debugging Python code that imports `screamingface` (`import screamingface as sf`). Covers composing fusions with `sf.Fanout`, `sf.Synthesize` and the reducers, evaluating them on a benchmark, connecting providers, reading reports and costs, and sharing a run as a url4. Generated from the ScreamingFace Client docs, version {{version}}.
---

# ScreamingFace Client

`screamingface` is the Python library of the ScreamingFace Client. You compose models into a fusion, evaluate it on a benchmark, and read the score and the cost.

Docs version: {{version}}. This skill is generated from https://docs.screamingface.ai. The index below links to each docs page and to its sections. Every page is also served as Markdown: add `.md` to its address.

## Before you write code

- Python 3.12 or newer. In a notebook, `!pip install "screamingface[notebook]"`. From a terminal, `uv pip install "screamingface[notebook]"`. The `[runtime]` extra adds the local engine. See [Installation](https://docs.screamingface.ai/sf-client/installation).
- The Client never calls a model provider itself. It needs an engine: a hosted one (access is granted by the OpenMined team) or one on your own machine, started with `screamingface up`, which uses your own provider keys.
- A local engine started with `screamingface up` serves one benchmark, `medxpert`. The hosted engine serves the others.
- On a hosted engine, log in with `client.login()` on a `sf.Client(engine_url=...)`. See [Installation](https://docs.screamingface.ai/sf-client/installation) and [Connections](https://docs.screamingface.ai/sf-client/guides/connections).

## Rules

1. Build a fusion as a chain: `sf.Fanout([model_a, model_b]) >> sf.Synthesize("provider/model")`. A reducer such as `sf.Vote()` can end the block in place of `sf.Synthesize`. See [Fusions](https://docs.screamingface.ai/sf-client/guides/fusions) and [Reducers](https://docs.screamingface.ai/sf-client/api/reducers).
2. Pass `benchmark=` to every `sf.evaluate` call. It has no default. Use `limit=` while you iterate: it caps the case count and is the main cost control. See [Running an evaluation](https://docs.screamingface.ai/sf-client/guides/running-an-evaluation).
3. A run is paid on your own provider keys when you use a local engine. Read the cost from `report.usage.cost_usd`. See [Usage](https://docs.screamingface.ai/sf-client/api/usage).
4. Use only names in `sf.__all__`. [The sf namespace](https://docs.screamingface.ai/sf-client/api/modules) lists the modules, and the API reference pages in the index list every public name.
5. Read an error by its code. [Errors](https://docs.screamingface.ai/sf-client/api/errors) lists the classes and the codes.

## Index

{{index}}

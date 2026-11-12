---
name: screamingface
description: Use when writing, running or debugging Python code that imports `screamingface` (`import screamingface as sf`). Covers composing fusions with `sf.Fanout`, `sf.Synthesize` and the reducers, evaluating them on a benchmark, connecting providers, reading reports and costs, and sharing a run as a url4. Generated from the ScreamingFace Client docs, version 0.1.12.
---

# ScreamingFace Client

`screamingface` is the Python library of the ScreamingFace Client. You compose models into a fusion, evaluate it on a benchmark, and read the score and the cost.

Docs version: 0.1.12. This skill is generated from https://docs.screamingface.ai. Each docs page is one Markdown file in `references/`, and the index below lists them all.

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

### Overview

- [Overview](references/sf-client.md): Open infrastructure for composing, measuring and sharing model fusions.

### Tutorials

- [Installation](references/sf-client-installation.md): Install the Client and point it at an engine, hosted or one you run yourself.
- [Your first fusion](references/sf-client-first-fusion.md): Combine two models into one, run it on a benchmark, and read the score.
- [Reproduce OpenRouter's DRACO results](references/sf-client-reproduce-draco.md): Run a DRACO subset end to end to compare fusions with its solo models.

### How-to guides

- [Connections](references/sf-client-guides-connections.md): Connect a model provider through the engine, and log in to a hosted one.
- [Models](references/sf-client-guides-models.md): Select a model route and set the answer policy a candidate owns.
- [Map-reduce for fusions](references/sf-client-guides-map-reduce.md): A fusion can dispatch a question to its member models, then map, filter and reduce what comes back into the one answer a benchmark grades. This page covers each stage and the signals that pass between them.
- [Fanout fusion](references/sf-client-guides-fusions.md): Combine members into one answer through a synthesizer.
- [Pipelines](references/sf-client-guides-pipelines.md): Chain recipes in series, so each stage refines the previous stage's answer.
- [Benchmarks](references/sf-client-guides-benchmarks.md): Discover the benchmarks an engine publishes and pick the protocol you want to run.
- [Running an evaluation](references/sf-client-guides-running-an-evaluation.md): Evaluate one or many candidates against a benchmark and get one Report.
- [Using the community's cache](references/sf-client-guides-community-cache.md): Pull the hosted community cache into a local engine, so your local runs answer calls the community has already made, for free.
- [Leaderboards](references/sf-client-guides-leaderboards.md): Browse ranked results, publish a CandidateResult, and pull the url4 back out.
- [Reproduce & share (url4)](references/sf-client-guides-reproduce-and-share.md): Read the exact plan a run executed, and hand it to someone else.
- [Clients](references/sf-client-guides-clients.md): The default Client behind sf.*, and when to build your own.
- [Install the agent skill](references/sf-client-agent-skill.md): Give a coding agent the ScreamingFace Client docs as a skill.

### Overview

- [Modules](references/sf-client-api-modules.md): The modules and functions you can call on sf directly.

### Classes

- [Clients](references/sf-client-api-clients.md): Client and AsyncClient: how you reach an engine.
- [Recipes](references/sf-client-api-recipes.md): The abstract Recipe base every candidate shares, where each concrete type is documented, and the corrective loops that draft under a benchmark's check.
- [Models](references/sf-client-api-models.md): The Model recipe class you build, and the discovery types routes come back as: ModelInfo, ModelDetails, and their fields.
- [Fusion](references/sf-client-api-fusions.md): Combine parallel members into one answer through a synthesizer.
- [Reducers](references/sf-client-api-reducers.md): The steps of a fan-out block: reducers, judges, narrow steps, a gate and declared signals.
- [Pipeline](references/sf-client-api-pipelines.md): Chain recipes in series, each stage refining the last.
- [Url4](references/sf-client-api-url4.md): The string value a run carries, and the editable Python it forks to.
- [Benchmarks](references/sf-client-api-benchmarks.md): Benchmark and the read-only values discovery returns.
- [Connections](references/sf-client-api-connections.md): The provider-connection values: Connection, the OAuth flows, and the interactive panel.
- [Reports](references/sf-client-api-reports.md): Report and everything it carries.
- [CandidateResult](references/sf-client-api-candidate-result.md): One candidate's outcome and the values it carries (MemberResult, OperationInfo, CaseResult), and the CaseGrade tree behind each case score.
- [Usage](references/sf-client-api-usage.md): Usage for token and cost accounting, and Failure for anything that went wrong.
- [Leaderboards](references/sf-client-api-leaderboards.md): The public board: what it holds, and what a submission records.
- [Events](references/sf-client-api-events.md): What a run reports through on_event while it is still running.
- [Errors](references/sf-client-api-errors.md): What the Client raises, and the warnings it emits when a run or a submission carries a caveat.

### Modules & types

- [Shared cache](references/sf-client-api-cache.md): Use the shared cache from the hosted engine when running locally.
- [Classify](references/sf-client-api-classify.md): Send one text to a text classifier and read its label scores.
- [Analytics](references/sf-client-api-analytics.md): Analytics controls for opting in and out, and what it collects.

### Overview

- [Architecture](references/learn.md): How the pieces fit (url4 the protocol, the engine that runs it, and the surfaces you compose from) and where each one lives in the codebase.

### Explanation

- [url4](references/learn-url4.md): The grammar and protocol that packages sources and an intent into one line, so a fusion runs, reproduces, and can be reused like a model call.
- [url4 SDK](references/learn-url4-sdk.md): The Python library for building, reading, and running url4 expressions.
- [Files in url4](references/learn-url4-files.md): Images and PDFs as url4 sources: file URLs, sha256 blob refs, what v1 refuses, and the limits.
- [ScreamingFace Engine](references/learn-engine.md): The runtime that turns a url4 expression into a result, and the trust boundary that holds the keys.
- [Caching and compute](references/learn-caching.md): What a run bills: call-level caching, a shared community cache, and where the compute comes from.
- [AI gateway](references/learn-ai-gateway.md): Where your provider keys live, encrypted, and the one endpoint the engine calls to reach every model provider.
- [Leaderboard](references/learn-leaderboard.md): The public board where ensemble results are ranked, and where every entry carries the recipe that produced it and whether the hosted engine ran it.

### Other pages

- [Compose model fusions. Reproduce every run from one line.](references/index.md)

# Your first fusion

Source: https://docs.screamingface.ai/sf-client/first-fusion

Combine two models into one, run it on a benchmark, and read the score.

A fusion is a composed system of different models, working as one. In this tutorial you build one, run it on three benchmark cases, and read its score.

Note: You need the Client installed (see [Installation](sf-client-installation.md)) and an engine to run on. On the hosted engine your account needs access, which the OpenMined team grants, and no provider keys are needed. On a local engine you connect your own OpenRouter key. Step 2 shows both.

## 1 · Import the library

Everything you need hangs off the top-level `sf` module.

```python
import screamingface as sf
```

## 2 · Connect to an engine

**Hosted engine**

The hosted engine runs on compute the OpenMined team allocates to your account, so there is no key to paste. Call `sf.connect()` to open the connection panel. It shows a Log in button; log in through your browser. For an account with access the panel then lists OpenRouter as connected. For an account without access every provider shows as unavailable, and an evaluation is refused: ask the OpenMined team for access, or use your own engine.

```python
sf.connect()  # opens the connection panel; click Log in
```

**Your own engine**

Start the local stack as described in [Installation](sf-client-installation.md), point the Client at it, and connect your own OpenRouter key. A local engine needs no login.

```python
sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
sf.connect("openrouter", api_key="sk-or-...")  # your own OpenRouter key
```

## 3 · Build the fusion

Give `sf.Fanout` two model routes. The two members answer the same question in parallel. Then `>>` adds `sf.Synthesize`, the synthesizer: it reads both drafts and writes the single answer that gets graded. Here the first model doubles as the synthesizer. Recipes also compose into routed ensembles and into sequential cascades and gates.

```python
fusion = sf.Fanout(
    ["openrouter/openai/gpt-5.5", "openrouter/google/gemini-3-flash-preview"],
) >> sf.Synthesize("openrouter/openai/gpt-5.5")
```

## 4 · Run it

`sf.evaluate` runs your fusion against a benchmark and grades the answers. `limit=3` runs three cases.

**Hosted engine**

`ifeval` checks whether a model follows instructions, graded by deterministic verification.

```python
report = sf.evaluate(fusion, benchmark="ifeval", limit=3)
```

**Your own engine**

A local engine comes with `medxpert` ready to run: 2,450 expert-level medical multiple-choice questions, graded by exact match against the published key, so no judge model is called.

```python
report = sf.evaluate(fusion, benchmark="medxpert", limit=3)
```

Note: A local engine started with `screamingface up` comes with `medxpert` ready to run; the hosted engine serves the full set (`ifeval`, `draco` (deep research) and more) with no setup. To run more benchmarks on a local engine, run `just local-stack-notebooks` from `packages/screamingface/` in a repository checkout. List what an engine serves with `sf.benchmarks.list()`, and see [Choose a benchmark](sf-client-guides-benchmarks.md) for how to pick one.

## 5 · Read the score

The run comes back as a [Report](sf-client-api-reports.md). You gave it one candidate, so `report.candidates.only` is your fusion, and its `score` is the fraction of cases it got right, and higher is better. On `medxpert` with `limit=3` the fusion answered two of three correctly. The run cost $0.4662255, read from `report.usage.cost_usd`:

```python
candidate = report.candidates.only
candidate.score, report.usage.cost_usd
```

```
(0.6667, Decimal('0.4662255'))
```

That is a whole evaluation: compose, run, read. The same three steps scale from three cases to a full benchmark.

## How far this goes

What you built is a **parallel fan-out**: each member answers the question on its own and a synthesizer folds their drafts into one. That is one of two ways recipes compose. The other is a [Pipeline](sf-client-api-pipelines.md), the serial counterpart, where each stage refines the previous stage's answer instead of running alongside it.

Recipes nest, so these two types compose into much larger systems. A member, a synthesizer, or a pipeline stage can itself be a [Fusion](sf-client-api-fusions.md) or a Pipeline: a fusion of pipelines, a pipeline whose last stage is a fusion, a fusion whose synthesizer is itself a fusion. Every one is built from those same two moves, parallel and serial. Start flat, like here, and add depth when a task needs it.

## Where to go next

-   **[Compose a candidate](sf-client-guides-fusions.md)**: weights, judges, and nesting fusions inside fusions.
-   **[Reproduce DRACO state-of-the-art](sf-client-reproduce-draco.md)**: put a fusion up against its solo models on a real board.
-   **[Fusion reference](sf-client-api-fusions.md)**: every field and argument, in full.

# Overview

Source: https://docs.screamingface.ai/sf-client

Open infrastructure for composing, measuring and sharing model fusions.

ScreamingFace is an open-source, Python-first toolkit for composing model **fusions** (ensembles, routed ensembles, cascades, etc.) and measuring them as a single system with uniform grading. It is built around one goal: advancing capability by composition, combining existing models rather than training new ones. You assemble a fusion from providers you hold keys for, evaluate it against a research benchmark, and read back its score next to its cost.

A fusion of models can outscore every model inside it. In a reproduction of the **DRACO** deep-research benchmark, the best fusion reached **68.6%**, while the best single model managed **60.2%** ([published results](https://andrewtrask.substack.com/p/6-weeks-ago-frontier-ai-labs-lost)). This isn't a one-off. The same pattern shows up throughout the ensemble literature, for example in [*Beyond Leaderboards: Tokenomics of Agentic Small Language Model Ensembles*](https://openreview.net/forum?id=XSIYfTm2h7) (Skurikhin et al., Los Alamos). The ScreamingFace Client and Leaderboard grade every system the same way and show its score next to its cost, and each result carries its url4.

## What the Client and Leaderboard provide

-   **Held-out grading:** The engine grades each case, so a score does not rest on trusting whoever produced it. The run report returns the rubric criteria and the judge model for each graded case, so you can see how a score was reached.
-   **A reproducible artifact for every run:** Each evaluation compiles to one [url4](learn-url4.md) expression recording the models, their parameters, and the benchmark revision that was used. Anyone holding it can run the same evaluation.
-   **Your own providers (local engine):** You connect the API keys you already have, and calls are billed to your own accounts rather than resold to you.
-   **Billing only for new calls:** With the [cache](learn-caching.md) on, a model call that was made before is served from the cache. Calls are matched by route, prompt and parameters, so comparing many fusion candidates over one benchmark is billed only for the calls that have not been made before. An identical call from another candidate is served from the cache, and swapping one member re-uses the member calls that did not change.
-   **Cost reported alongside accuracy:** Tokens, spend, and duration stream while the run is in progress and are totalled per model and per fusion, so the price of a gain is visible at the same time as the gain.
-   **Reusable recipes:** Recipes published to the leaderboard can be imported, modified, and re-run, and on a hosted engine the cache is shared across the community, so calls already in the shared cache cost nothing to repeat.

## How it works

The Client compiles your fusion into one **url4** expression and hands that to an [engine](learn-engine.md), which holds the credentials and the benchmark answer keys and does the grading.

A **url4** is a single-line expression, following a fixed grammar and protocol, that describes a composed system: which models take part, how their answers are combined, and what each one is asked to do. It is both the record of what ran and the instruction for running it again, so a published result carries its own method instead of describing it in prose.

From there the engine resolves the expression, calls each model, applies the benchmark's grader, and streams usage back while the run proceeds. What returns is the set of scores, any failures, and the total cost. Because the url4 travels with the result, someone else can repeat the evaluation and compare what they get against what you reported.

[Diagram: Local request flow: the Client compiles your fusion into one url4 expression and hands it to an engine on your own machine, which fans each model call out through the AI gateway to the providers you hold keys for and streams scores and cost back.]

**The local flow.** The Client hands your fusion to an engine on your own machine, which fans model calls through the gateway to the providers you hold keys for. Its cache accumulates across runs and can pull from the shared community cache, and the engine submits a verifiable result to the public leaderboard.

## Two ways to run

You point the Client at an engine in one of two places.

-   **A local engine** ships with the toolkit and runs on your own machine, using your keys and its own cache. Nothing is hosted and no third party sits between you and your providers, but the cache starts empty and you pay for the compute. `sf.cache.pull_from_remote()` signs in to the hosted engine and copies the community cache into it.
-   **A hosted engine** runs the same software as a service and adds the shared community cache, on compute we provide once your account has been given access. To get access, reach out to the OpenMined team. It does not take your own provider keys; bring-your-own-key is the local path, and your prompts run on an engine we operate.

The code you write is the same either way. Only the `configure` call (the engine and leaderboard URLs) and the benchmarks the engine serves differ, so the decision is reversible. The [Installation](sf-client-installation.md) guide covers both.

## The smallest example

This runs on a hosted engine, which requires permission. You can run the same thing by pointing the ScreamingFace Client at a local engine ([more here](sf-client-installation.md)).

```python
import screamingface as sf

sf.configure(
    engine_url="https://fusion.screamingface.ai",
    scoreboard_url="https://leaderboard.screamingface.ai",
)

gpt = sf.Model("openrouter/openai/gpt-5.5")
flash = sf.Model("openrouter/google/gemini-3-flash-preview")
fusion = sf.Fanout([gpt, flash]) >> sf.Synthesize("openrouter/openai/gpt-5.5")

# Score the solo model beside the fusion, on the same cases.
report = sf.evaluate([gpt, fusion], benchmark="draco-3pass", limit=3)
{c.name: c.score for c in report.candidates}
```

`score` is each candidate's benchmark score over the same cases, where higher is better. The report carries no baseline or gain field, because the comparison is simply that you ran the solo model and the fusion in one call and can read both numbers. Scores for `draco-3pass` are on the live [leaderboard](https://leaderboard.screamingface.ai/benchmark.html?id=draco-3pass).

# Models

Source: https://docs.screamingface.ai/sf-client/guides/models

Select a model route and set the answer policy a candidate owns.

A **Model** names one model route and, optionally, the answer policy that route should use. It is the smallest thing you can evaluate, and the building block every [Fusion](sf-client-guides-fusions.md) is made of.

A Model is **immutable**. Constructing one makes no request and needs no connection: it is a value describing what to ask for. Nothing happens until you pass it to an evaluation.

## What you can do with it

-   Select a route to evaluate.
-   Name a Model so two samples of the same route stay distinguishable.
-   Override the answer prompt and generation parameters.
-   List the routes this engine can actually reach.
-   Read one route's details to see which parameters and tools it supports.

## Main APIs

| API | What it does |
| --- | --- |
| `sf.Model(model, *, name=None, prompt=None, params=None)` | Selects one model route as the smallest thing you can evaluate, optionally overriding its answer policy with a prompt and generation parameters. |
| `sf.models.list()` | Lists the routes this engine can reach as `sf.ModelInfo` values, spanning every provider the engine knows. |
| `sf.models.get(model_id)` | Returns one route's `sf.ModelDetails`: which parameters and tools it supports, and whether the details are current. |
| `.name` · `.model` · `.prompt` · `.params` | Read back what a Model resolved to, including its inferred or explicit name. |

## How to

### 1 · Select a route

The route is the only required argument. The Model's `name` is inferred from its last segment, which is what appears in a report.

```python
import screamingface as sf

opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
opus
```

```
Model('openrouter/anthropic/claude-opus-4.8')
```

### 2 · Name an independent sample

Two Models on the same route with the same policy are the *same* candidate: [the engine](learn-engine.md) deduplicates them by content inside one compiled graph. An explicit `name` is how you say you meant two independent samples, and it is the name the report uses.

```python
sf.Model("openrouter/openai/gpt-5.5", name="gpt-run-2")
```

```
Model('openrouter/openai/gpt-5.5', name='gpt-run-2')
```

### 3 · Override the answer policy

The SDK supplies a general answer prompt, so a bare Model works. When an experiment needs something specific, `prompt` and `params` replace it.

```python
sf.Model(
    "openrouter/openai/gpt-5.5",
    prompt="Answer concisely.",
    params={"max_tokens": 1024},
)
```

```
Model('openrouter/openai/gpt-5.5', prompt='Answer concisely.', params={'max_tokens': 1024})
```

These are **candidate-owned** settings: they change how your candidate answers, and they can never touch benchmark-owned cases, judge models, grading or aggregation. That separation is what keeps two candidates comparable on the same benchmark. Whatever you set is resolved and embedded in the run's [url4](learn-url4.md), so a report records the policy that actually ran.

### 4 · See what the engine can reach

```python
sf.models.list()
```

```
ModelInfo('anthropic/claude-opus-5', provider='anthropic', parameters=5, tools=1)
ModelInfo('anthropic/claude-opus-4-8', provider='anthropic', parameters=5, tools=1)
ModelInfo('anthropic/claude-opus-4-7', provider='anthropic', parameters=5, tools=1)
ModelInfo('anthropic/claude-opus-4-6', provider='anthropic', parameters=5, tools=1)
ModelInfo('anthropic/claude-opus-4-5', provider='anthropic', parameters=5, tools=1)
ModelInfo('anthropic/claude-fable-5', provider='anthropic', parameters=5, tools=1)
ModelInfo('anthropic/claude-sonnet-5', provider='anthropic', parameters=5, tools=1)
ModelInfo('anthropic/claude-sonnet-4-6', provider='anthropic', parameters=7, tools=1)
…   # 110 entries across 6 providers on a local engine
```

Two things to note. The catalogue spans **every provider the engine knows**, not only the ones you have connected: a route you have no credential for will fail at evaluation, not here. The hosted engine lists more routes than a local one (112 against 110). And ID shapes differ per provider: `anthropic/claude-opus-4-8` against `openrouter/anthropic/claude-opus-4.8`. Copy the `id` rather than retyping it.

> **The catalogue is fixed.** The engine does not discover models automatically, so only the routes listed here can be used to build fusions, and a model missing from the list can't be added from the Client.

### 5 · Check that a route accepts your policy

`sf.models.get(id)` returns the fuller `sf.ModelDetails` for one route: each parameter with its schema and whether the gateway currently projects it, the tools and transports it supports, and whether the details are stale. Consulting it is how you learn that `params={"max_tokens": 1024}` is available on a route before a run spends anything. Which parameters a route accepts ultimately depends on the provider: a provider can reject a parameter its details list, and the run then fails with `provider_error`.

```python
gpt = sf.models.get("openrouter/openai/gpt-5.5")
gpt.parameters["temperature"].enabled, sorted(gpt.tools)
```

```
(True, ['function'])
```

### 6 · Discover a route's parameters

The same `ModelDetails` is also how you find out *what* a route lets you configure. `details.parameters` is a mapping keyed by parameter name, so listing its keys enumerates every knob the route exposes.

```python
gpt = sf.models.get("openrouter/openai/gpt-5.5")

# What can I configure on this route?
len(gpt.parameters), sorted(gpt.parameters)[:4]
```

```
(23, ['frequency_penalty', 'logprobs', 'max_tokens', 'n'])
```

Each value is an `sf.ModelParameter`. Its `schema` gives the type and the bounds the gateway enforces (a numeric `minimum`/`maximum`, an `enum` of allowed values, a `max_length`), while `enabled` says whether the gateway currently honours it. Reading the schema tells you a value's legal range before you set it in `params`.

```python
temp = gpt.parameters["temperature"]

# Each parameter carries a schema: type, bounds, and any fixed value set.
temp.schema.type, temp.schema.minimum, temp.schema.maximum, temp.enabled
```

```
('number', 0.0, 2.0, True)
```

A parameter that isn't listed isn't configurable on that route: setting it in `params` is refused at pre-flight with `PlanningError` rather than silently dropped, so a typo costs you nothing. For example, `params={"reasoning": "high"}` on `openrouter/openai/gpt-5.5` raises `PlanningError: Parameter 'reasoning' is not available`.

## Links

-   [Companion notebook: `00_quickstart.ipynb`](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb)

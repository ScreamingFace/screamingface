# Fanout fusion

Source: https://docs.screamingface.ai/sf-client/guides/fusions

Combine members into one answer through a synthesizer.

A **fusion** sends the same question to all its members, then a **synthesizer** reads their answers and produces one final answer. The benchmark grades that final answer, so a fusion competes with a solo [Model](sf-client-guides-models.md).

You build a fusion as a chain of two steps. `sf.Fanout(members)` sends the question to every member. `sf.Synthesize(model)` is the synthesizer. `>>` joins the two steps into one recipe.

The synthesizer is itself a recipe. Usually it is a model that reads the candidate answers and writes the winner. It can also be a [Pipeline](sf-client-guides-pipelines.md) or another fusion. Synthesis composes the same way members do.

[Diagram: A fusion sends one question to several members; a synthesizer combines their answers into the single answer the benchmark grades.]

Members answer the same question; the synthesizer combines them into the one answer the benchmark grades.

Like a Model, a fusion is immutable. Building one makes no requests.

## What you can do

-   Combine two or more Models into one candidate.
-   Pick your synthesizer. Control how a model synthesizer is prompted.
-   Nest a fusion or a Pipeline inside another fusion.
-   Read back the steps, the members and the resolved name.

## Main APIs

| API | What it does |
| --- | --- |
| `sf.Fanout(members, *, signals=None, quorum="all", name=None, prompt=None)` | Sends the question to every member in parallel. It opens a block. A synthesizer (or a reducer) closes the block. |
| `sf.Synthesize(model, *, prompt=None)` | The synthesizer. It reads the members' answers and writes one final answer for the benchmark to grade. A route string or `sf.Model` has a model write the answer. An [`sf.Pipeline`](sf-client-guides-pipelines.md) or another fusion gives multi-step synthesis. |
| `a >> b` | Joins steps left to right and returns an `sf.Pipeline`. `sf.Fanout(...) >> sf.Synthesize(...)` is a fusion. |
| `.name` · `.steps` | Read back the resolved name and the steps: the `Fanout` step, then the `Synthesize` step. |
| `sf.Recipe` | The shared base type of every candidate kind. |

## How to

### 1 · Combine two models

`sf.Fanout` takes the members first (positional). `sf.Synthesize` takes the synthesizer. The value shows in the same `Fanout(...) >> Synthesize(...)` form.

```python
import screamingface as sf

opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
gpt = sf.Model("openrouter/openai/gpt-5.5")

pair = sf.Fanout([opus, gpt]) >> sf.Synthesize("openrouter/anthropic/claude-opus-4.8")
pair
```

```
Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5']) >> Synthesize('openrouter/anthropic/claude-opus-4.8')
```

[Diagram: The pair fusion sends the question to opus and gpt; opus, reused as the synthesizer, writes the graded answer.]

`pair` asks opus and gpt the same question; opus, reused as the synthesizer, writes the one answer the benchmark grades.

A fusion needs at least one member. An empty member list fails when you build it. A `sf.Fanout` also needs a step after it. A chain that ends after `sf.Fanout` fails when you compile or evaluate it, before any spend.

### 2 · Read the resolved name

Without an explicit `name` on `sf.Fanout`, the fusion's name is its members' names joined with `+`. Reports show that name. `.steps` holds the two steps: the `Fanout`, then the `Synthesize`.

```python
fanout, writer = pair.steps
pair.name, [m.name for m in fanout.members]
```

```
('claude-opus-4.8+gpt-5.5', ['claude-opus-4.8', 'gpt-5.5'])
```

### 3 · Choose the synthesizer

The **synthesizer** decides how the members' answers become one. It is itself a recipe. Give `sf.Synthesize` a route string or `sf.Model` to have a model read the drafts and write the final answer. Or give it an [`sf.Pipeline`](sf-client-guides-pipelines.md) or another fusion for multi-step synthesis. Swapping synthesizers is the main lever: same members, different synthesizer, different candidate.

```python
sf.Fanout([opus, gpt], name="pair-gpt-synth") >> sf.Synthesize(
    sf.Model(
        "openrouter/openai/gpt-5.5",
        prompt="Write the final answer from the drafts.",
    )
)
```

```
Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5'], name='pair-gpt-synth') >> Synthesize(Model('openrouter/openai/gpt-5.5', prompt='Write the final answer from the drafts.'))
```

[Diagram: The same two members, opus and gpt, but now gpt with its own prompt is the synthesizer that writes the graded answer.]

Same members, different synthesizer: swap in gpt (with its own prompt) and it is a different candidate, though opus and gpt still answer as members.

A model synthesizer has its own `prompt` and `params`. They control how it writes the final answer, separate from how members answer. Set a different prompt on a member by setting it on that Model. `sf.Synthesize(model, prompt=...)` also sets the synthesizer prompt, when the model has no prompt of its own. `sf.Fanout(members, prompt=...)` sets the prompt of each member that has none.

A model synthesizer is one way to close the block. A **reducer** closes it with a rule instead of a newly written answer: `sf.Vote()`, for instance, returns the answer most members agree on, unchanged. The [map-reduce](sf-client-guides-map-reduce.md) guide covers the full set of reducers, judges and narrow steps, and the [Reducers reference](sf-client-api-reducers.md) has their signatures.

### 4 · Nest a fusion

A member can be a fusion or a Pipeline, so a pair can become a member in a larger fusion. The inner recipe shows up in full inside the outer `Fanout`.

```python
haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")

sf.Fanout([pair, haiku], name="nested") >> sf.Synthesize("openrouter/openai/gpt-5.5")
```

```
Fanout([Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5']) >> Synthesize('openrouter/anthropic/claude-opus-4.8'), 'openrouter/anthropic/claude-haiku-4.5'], name='nested') >> Synthesize('openrouter/openai/gpt-5.5')
```

[Diagram: The nested fusion: the pair fusion (opus and gpt combined by opus) and haiku are the two members; gpt synthesizes their answers into the graded answer.]

The `nested` fusion has two members, the `pair` fusion and haiku, and gpt synthesizes their answers. The inner pair shows up under its own resolved name.

Members must be recipes: a `Model`, a `Pipeline`, or another fusion (or a route string, which becomes a `Model`).

### 5 · Handle partial grading failures

When you run a fusion, a member can fail. A provider times out, a key is rejected, or a route is unavailable. By default `quorum` is `"all"`, so every member must answer: one failure fails the whole fusion, the synthesizer never runs, and the candidate scores nothing for that question. Two controls let the fusion tolerate a failure and still produce a graded answer.

**Set a quorum.** `quorum` on `sf.Fanout` sets how many members must succeed. With `quorum=2` on three members, the fusion proceeds as soon as any two answer, and the synthesizer reads the answers that arrived. It accepts `"all"` (the default) or a number from 0 to the member count.

**Mark members optional.** A member built with `optional=True` may fail without stopping the fusion. Its failure is tolerated, and it drops out of the answers the synthesizer reads. A member left required (the default) must succeed: if a required member fails, the fusion fails even when the quorum could otherwise be met. Below, two frontier models are required and a faster model is optional, so the fusion survives losing it as long as the quorum of two is met.

```python
sf.Fanout(
    [opus, gpt, sf.Model("openrouter/google/gemini-3.1-flash-preview", optional=True)],
    quorum=2,
) >> sf.Synthesize("openrouter/anthropic/claude-opus-4.8")
```

```
Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5', Model('openrouter/google/gemini-3.1-flash-preview', optional=True)], quorum=2) >> Synthesize('openrouter/anthropic/claude-opus-4.8')
```

[Diagram: Topology: members A and B succeed and member C, optional, fails; the quorum check passes the answers that arrived to the Synthesize step when enough members succeeded, and the candidate fails when the quorum is not met or a required member failed.]

Which members reach the synthesizer, and where a failure stops the candidate.

### 6 · Use the `sf.Fusion` shortcut

`sf.Fusion` is a shortcut for the same chain. It takes the members, then the synthesizer as a keyword. It returns an equal value with the same url4. The value shows in the `Fanout(...) >> Synthesize(...)` form. It also takes `signals`, `quorum`, `name` and `prompt` for the `sf.Fanout`, and `optional=True`, which wraps the chain as `sf.Pipeline([...], optional=True)`. It refuses `optional=True` with a narrow step (`sf.Rank`, `sf.Filter`, `sf.Concat`) as the synthesizer, because an optional chain must be a closed block. It refuses a bare `sf.Judge` as the synthesizer, because a judge only scores.

```python
same = sf.Fusion([opus, gpt], synthesizer="openrouter/anthropic/claude-opus-4.8")
same == pair
```

```
True
```

## The building blocks

### `sf.Fanout`

```python
sf.Fanout(
    members: Sequence[str | Recipe],
    *,
    signals: Mapping[str, SignalSource] | None = None,
    quorum: int | Literal["all"] = "all",
    name: str | None = None,
    prompt: str | None = None,
)
```

| Name | Type | Meaning |
| --- | --- | --- |
| `members` | `Sequence[str | Recipe]` | One or more members, in order. Each can be a route string, a `Model`, a `Pipeline`, or another fusion. Ensembles nest. |
| `signals` | `Mapping[str, SignalSource] | None` | Named numbers that the run measures from each member answer. A later step of the same block reads them. `sf.Synthesize` right after `sf.Fanout` reads no signal, so that block refuses `signals`. |
| `quorum` | `int | "all"` | The least number of members that must answer: `"all"` (the default) or a number from 0 to the member count. |
| `name` | `str | None` | Defaults to the member names joined with `+`, for example `claude-opus-4.8+gpt-hot`. The fusion takes this name. |
| `prompt` | `str | None` | Sets the prompt of each member that is a route string or a `Model` with no prompt. A member that has its own prompt is refused. |

### `sf.Synthesize`

```python
sf.Synthesize(
    model: str | Recipe,
    *,
    prompt: str | None = None,
)
```

| Name | Type | Meaning |
| --- | --- | --- |
| `model` | `str | Recipe` | The synthesizer: a route string or any recipe (a `Model`, a `Pipeline`, or another fusion). It reads the members' answers and writes the final one. |
| `prompt` | `str | None` | The synthesizer prompt. Use it only with a route string or a `Model` that has no prompt. With no prompt, the default synthesis prompt applies. |

### Attributes

A fusion is an `sf.Pipeline`. Its `steps` is a `tuple`: the `Fanout` step, then the `Synthesize` step. Its `name` is the resolved label of the `Fanout`. The `Fanout` step keeps `members` (a `tuple` in the order you gave, route strings become `Model`), `name`, `prompt`, `quorum` and `signals`. The `Synthesize` step keeps `model` (a route string becomes a `Model`) and `prompt`.

### Raises

| When | Error |
| --- | --- |
| The members are empty | `ValueError: a sf.Fanout requires at least one member` |
| `members` is not an ordered sequence (for example a bare route string) | `TypeError: sf.Fanout members must be an ordered sequence of model routes or Recipes` |
| A member is not a route string or a supported recipe | `TypeError: sf.Fanout member must be a model route, a sf.Model or a sf.Pipeline` |
| The synthesizer is not a route string or a supported recipe | `TypeError: sf.Synthesize model must be a model route, a sf.Model or a sf.Pipeline` |
| A recipe comes right after `sf.Fanout`, with no synthesizer between | `ValueError: a sf.Fanout block needs a reducer or sf.Synthesize before the next stage` |
| The chain ends after `sf.Fanout` (raised by compile and `sf.evaluate`, before any spend) | `ValueError: the chain ends inside a sf.Fanout block: add a reducer or sf.Synthesize` |
| `quorum` is above the member count | `ValueError: sf.Fanout quorum must be between zero and the member count` |

## Links

-   [Companion notebook: `00_quickstart.ipynb`](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb)

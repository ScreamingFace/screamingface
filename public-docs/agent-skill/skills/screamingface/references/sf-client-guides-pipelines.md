# Pipelines

Source: https://docs.screamingface.ai/sf-client/guides/pipelines

Chain recipes in series, so each stage refines the previous stage's answer.

A **Pipeline** is a recipe composed of an ordered list of **stages**. It doesn't run anything by itself; like every recipe, building one makes no requests. The stages run only during an [evaluation](sf-client-guides-running-an-evaluation.md): the first stage answers the case, and each later stage takes the *previous* stage's answer as its input (a draft gets reviewed, then polished). The benchmark grades only the last stage's answer, so a Pipeline competes head-to-head with a solo [Model](sf-client-guides-models.md) or a [Fusion](sf-client-guides-fusions.md).

A stage can be any recipe: a `Model`, a fusion (`sf.Fanout(...) >> sf.Synthesize(...)`), or another `Pipeline`. Refine, review, or re-rank as many times as your experiment needs. Like all recipes, a Pipeline is immutable. Building one makes no requests.

[Diagram: A Pipeline runs its stages in series: the first stage answers the case, each later stage takes the previous stage's answer as its input, and grading the last stage's answer produces the graded answer.]

The flow of information: the first stage answers the case, each later stage takes the previous stage's answer as its input, and grading the last stage's answer produces the graded answer.

Stage / memberFinal stage (synthesizer)Graded answerPipeline (dashed = unnamed, flattens)

## What you can do

-   Chain two or more recipes so each stage refines the previous answer.
-   Build the same chain with `>>`, which reads left to right.
-   Nest a Pipeline inside a fusion, or a fusion inside a Pipeline.
-   Read back the ordered steps and see the resolved name.

## Main APIs

| API | What it does |
| --- | --- |
| `sf.Pipeline(steps, *, name=None, optional=False)` | Runs stages one after another. Each stage gets the previous stage's answer, and the last stage's answer is what the benchmark grades. |
| `a >> b` | Joins two stages and returns a new `sf.Pipeline`. `a >> b >> c` reads left to right and returns a new `sf.Pipeline`. |
| `.name` · `.optional` · `.steps` | Read back the resolved name, the optional flag and the ordered steps (as a tuple). |
| `sf.Recipe` | The shared base type of every candidate kind. |

## How to

### 1 · Chain two recipes

Stages come first (positional), in the order they run. The Pipeline's name defaults to stage names joined with `->`. Give it an explicit `name` for a custom label in reports.

```python
import screamingface as sf

draft = sf.Model("openrouter/openai/gpt-5.5")
review = sf.Model("openrouter/anthropic/claude-opus-4.8")

chain = sf.Pipeline([draft, review], name="review-chain")
chain
```

```
Pipeline([Model('openrouter/openai/gpt-5.5'), Model('openrouter/anthropic/claude-opus-4.8')], name='review-chain')
```

[Diagram: The review-chain Pipeline holds draft then review; grading review's answer produces the graded answer.]

The review-chain Pipeline holds draft then review; grading review's answer is the graded answer.

### 2 · Build the same chain with `>>`

`>>` joins two stages, so a chain reads left to right. It builds the same Pipeline as the constructor: `draft >> review >> final` is equal to `sf.Pipeline([draft, review, final])`. A route string on the left also works.

```python
final = sf.Model("openrouter/openai/gpt-5.5", name="polish")

draft >> review >> final
```

```
Pipeline([Model('openrouter/openai/gpt-5.5'), Model('openrouter/anthropic/claude-opus-4.8'), Model('openrouter/openai/gpt-5.5', name='polish')])
```

[Diagram: One Pipeline of draft, review and final; grading final's answer produces the graded answer.]

`>>` builds one Pipeline of three stages; only the last stage's answer is graded.

### 3 · Flatten vs. nest

An *unnamed* Pipeline inside another Pipeline flattens into one sequence. Nesting for convenience never changes what runs.

```python
constructed = sf.Pipeline([draft, sf.Pipeline([review, final])])

[step.name for step in constructed.steps]
```

```
['gpt-5.5', 'claude-opus-4.8', 'polish']
```

[Diagram: The unnamed inner Pipeline (dashed) flattens into the outer Pipeline; grading the last stage's answer produces the graded answer.]

The unnamed inner Pipeline flattens into the outer one: draft → review → final runs as a single sequence.

Give the inner Pipeline a `name` and it is kept as a single stage instead, so a named chain stays a named, reusable unit.

```python
named = sf.Pipeline([review, final], name="polish-pass")

[step.name for step in (draft >> named).steps]
```

```
['gpt-5.5', 'polish-pass']
```

[Diagram: The named inner Pipeline polish-pass is kept as one stage inside the outer Pipeline; grading its last stage's answer produces the graded answer.]

A named inner Pipeline (polish-pass) stays one stage of the outer Pipeline: draft → polish-pass, itself review → final.

### 4 · Compose recursively

A stage is any recipe. A [fusion](sf-client-guides-fusions.md)'s members and synthesizer are any recipe too. So the two compose freely: a fusion of Pipelines, a Pipeline of fusions, or a fusion whose synthesizer is itself a Pipeline.

```python
judge = sf.Model("openrouter/anthropic/claude-opus-4.8", name="judge")
writer = sf.Model("openrouter/openai/gpt-5.5", name="writer")

sf.Fanout(
    [draft >> review, sf.Model("openrouter/google/gemini-3.1-pro-preview")],
) >> sf.Synthesize(sf.Pipeline([judge, writer]))
```

```
Fanout([Pipeline([Model('openrouter/openai/gpt-5.5'), Model('openrouter/anthropic/claude-opus-4.8')]), 'openrouter/google/gemini-3.1-pro-preview']) >> Synthesize(Pipeline([Model('openrouter/anthropic/claude-opus-4.8', name='judge'), Model('openrouter/openai/gpt-5.5', name='writer')]))
```

[Diagram: A fanout block whose members are a draft-to-review Pipeline and gemini, combined by a synthesizer that is itself a judge-to-writer Pipeline; grading the writer's answer produces the graded answer.]

A fanout block of two members, the draft → review Pipeline and gemini, combined by a synthesizer that is itself a judge → writer Pipeline; grading the writer's answer is the graded answer.

### 5 · Mix recipe types as stages

Because a stage is just a recipe, one Pipeline can mix a `Model`, a fusion, and a nested `Pipeline` as its stages. The unnamed `panel` chain flattens, so the output lists its two steps, `Fanout` and `Synthesize`. They still run as one stage. The named `refine` stays grouped. The last stage's answer is still what the benchmark grades.

```python
panel = sf.Fanout([draft, review]) >> sf.Synthesize(final)
refine = sf.Pipeline([review, final], name="refine")

sf.Pipeline([draft, panel, refine], name="mixed")
```

```
Pipeline([Model('openrouter/openai/gpt-5.5'), Fanout(['openrouter/openai/gpt-5.5', 'openrouter/anthropic/claude-opus-4.8']), Synthesize(Model('openrouter/openai/gpt-5.5', name='polish')), Pipeline([Model('openrouter/anthropic/claude-opus-4.8'), Model('openrouter/openai/gpt-5.5', name='polish')], name='refine')], name='mixed')
```

[Diagram: One Pipeline whose stages are a Model, a fanout block and a nested Pipeline; grading the last stage's answer produces the graded answer.]

A stage is any recipe: here a Model, a fanout block and a nested Pipeline chained in one Pipeline; only the last stage's answer is graded.

## The `Pipeline` class

```python
sf.Pipeline(
    steps: Sequence[str | Recipe | Step],
    *,
    name: str | None = None,
    optional: bool = False,
)
```

### Parameters

| Name | Type | Meaning |
| --- | --- | --- |
| `steps` | `Sequence[str | Recipe | Step]` | One or more steps, in order. Each can be a route string, any recipe, or a block step such as `sf.Fanout` or `sf.Synthesize`. An *unnamed* nested `Pipeline` flattens into the surrounding sequence; a *named* one stays as a single stage. |
| `name` | `str | None` | Defaults to the stage names joined with `->`, for example `gpt-5.5->claude-opus-4.8`. An empty string raises `ValueError: pipeline name must not be empty`. |
| `optional` | `bool` | Marks this Pipeline as optional when it is a member of a [Fusion](sf-client-guides-fusions.md), so the Fusion can succeed without it when its quorum is met. Default `False`. |
| `optional` | `bool` | Defaults to `False`. Set it to `True` for a chain that is an optional member of a `sf.Fanout`. |

### Attributes

`steps` is a `tuple` in canonical order. `name` is the resolved label. `optional` is the flag you gave. `a >> b` joins two stages and returns a new `Pipeline`.

### Raises

| When | Error |
| --- | --- |
| The stages are empty | `ValueError: a Pipeline requires at least one stage` |
| `steps` is not an ordered sequence (for example a bare route string) | `TypeError: Pipeline stages must be an ordered sequence of model routes or Recipes` |
| A stage (in `steps` or after `>>`) is not a route string, a recipe or a step | `TypeError: Pipeline stage must be a model route, a sf.Model or a sf.Pipeline` |

## Links

-   [Recipe composition in the package README](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/README.md)

# Pipeline

Source: https://docs.screamingface.ai/sf-client/api/pipelines

Chain recipes in series, each stage refining the last.

A Pipeline is a [Recipe](sf-client-api-recipes.md) that passes one input through an ordered sequence of stages; each stage refines the previous stage's answer, and the last stage's answer is graded. Like every recipe it is frozen and holds no Client. The [Pipelines guide](sf-client-guides-pipelines.md) walks through building one.

```python
sf.Pipeline(
    steps: Sequence[str | Recipe | Step],
    *,
    name: str | None = None,
    optional: bool = False,
)
```

| Attribute | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | The pipeline's name. Inferred by joining stage names with `->` unless you pass one. |
| `optional` | `bool` | `True` for a chain that is an optional member of a `sf.Fanout`. Defaults to `False`. |
| `steps` | `tuple` | The ordered steps, each refining the previous answer. At least one. A fusion block shows as its `Fanout` and `Synthesize` steps. |
| `optional` | `bool` | Whether this Pipeline, as a Fusion member, may fail without stopping the Fusion while its [quorum](sf-client-api-fusions.md) is met. |

Note: An unnamed Pipeline nested inside another flattens into the outer pipeline's stages; a Pipeline you give an explicit `name` stays grouped as one stage. Naming is behavioral, not cosmetic: it participates in equality, so two pipelines with the same stages but different naming are not equal.

`a >> b` joins two stages and returns a Pipeline. `a >> b >> c` reads left to right and returns a new `sf.Pipeline`. See [Recipe](sf-client-api-recipes.md).

```python
pipeline = sf.Pipeline(
    ["openrouter/deepseek/deepseek-v4-flash", "openrouter/z-ai/glm-5.2"],
)
report = sf.evaluate(pipeline, benchmark="medxpert", limit=1)
```

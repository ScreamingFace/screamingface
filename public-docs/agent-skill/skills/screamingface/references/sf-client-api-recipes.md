# Recipes

Source: https://docs.screamingface.ai/sf-client/api/recipes

The abstract Recipe base every candidate shares, where each concrete type is documented, and the corrective loops that draft under a benchmark's check.

A recipe tells ScreamingFace how to produce one answer: that's what a benchmark grades. This page documents `Recipe`, the abstract base every candidate shares. The three concrete types each have their own home: a single model route in [Models](sf-client-api-models.md), several members combined by a synthesizer (`sf.Fanout(...) >> sf.Synthesize(...)`) in the [Fusions guide](sf-client-guides-fusions.md), and stages chained in series in the [Pipelines guide](sf-client-guides-pipelines.md).

Every constructible recipe is frozen and holds no client. Building one makes no network requests, so you can compose them before connecting to anything. Recipes nest: a fusion or a `Pipeline` can contain a `Model`, another fusion, or another `Pipeline`, in any combination.

Note: Recipes compare by value. Two recipes built with identical arguments are equal, and [the engine](learn-engine.md) treats them as one candidate. Give a `Model` an explicit `name` for an independent sample. Recipes are unhashable: you can't use them as dict keys or put them in sets.

```python
a = sf.Model("openrouter/deepseek/deepseek-v4-pro")
b = sf.Model("openrouter/deepseek/deepseek-v4-pro")

a == b
```

```
True
```

## Recipe

`Recipe` is the abstract base the concrete types inherit from. You can't instantiate it directly. It exists for type annotations and so a `Fanout` or a `Pipeline` can hold a mixed list of members.

Every recipe has one public attribute: `name` (a `str`). `a >> b` joins two recipes and returns a [Pipeline](sf-client-guides-pipelines.md). A corrective loop is a whole candidate: it cannot be a stage.

Calling `sf.Recipe()` directly raises:

```
TypeError: Can't instantiate abstract class Recipe without an implementation for abstract method '_recipe_marker'
```

## Where each type is documented

-   **[Model](sf-client-api-models.md)**: a single model route. Its constructor, parameters, attributes, and errors live on the Models page.
-   **[Fusion](sf-client-guides-fusions.md)**: members combined by a synthesizer, built with `sf.Fanout` and `sf.Synthesize`. The Fusions guide carries its full reference.
-   **[Pipeline](sf-client-guides-pipelines.md)**: stages chained in series. The Pipelines guide carries its full reference.

## Corrective loops

Two further recipes, documented here, draft under the benchmark's own check and retry until a draft passes. Members draft in parallel; the benchmark marks each draft; the first passing draft is submitted word for word. A round where nothing passes makes one judge coaching call and a retry, up to `max_rounds`, which is a cost cap and not a target. The whole loop compiles into one candidate expression on the client, so it runs on any benchmark that advertises a check.

The two corrective recipes are the bottom row of a small grid: the same models, run with or without a correction loop.

|  | Solo | Panel |
| --- | --- | --- |
| **No loop** | `Model` | `Fanout >> Synthesize` |
| **Corrective** | `SelfCorrective` | `CorrectiveLoop` |

Note:`medxpert`, the benchmark a local engine started with `screamingface up` serves, does not support mid-run checking: a corrective candidate on it raises `PlanningError`. Run corrective candidates on a hosted benchmark that advertises a check, such as `ifeval`.

Note: What a correction round costs depends on the benchmark's check surface. A deterministic verifier such as `ifeval` checks every draft without a model call, so only the correction rounds add model calls. A rubric-graded benchmark such as `healthbench-worst30` or `draco` makes a judge call per draft on every round, first-round pass included, and `max_rounds` caps that.

[Diagram: Members draft in parallel; the benchmark check marks each draft; the first passing draft is submitted verbatim. A round where nothing passes returns to the members through a judge coaching call, retried up to max_rounds.]

### CorrectiveLoop

A panel of members drafting under the check. The single `judge` plays two roles the loop keeps apart: it selects among passing drafts, and it coaches after a no-pass round. It never writes the answer itself. A panel needs at least two members.

```python
sf.CorrectiveLoop(
    members: Sequence[str | Recipe],
    *,
    judge: str | Recipe,
    max_rounds: int = 3,
    name: str | None = None,
)
```

| Attribute | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | The loop's name. Inferred by joining member names with `+` unless you pass one. |
| `members` | `tuple[Recipe, ...]` | The panel that drafts. At least two. |
| `judge` | `Recipe` | Selects among passing drafts and coaches after a no-pass round. Never writes the answer. |
| `max_rounds` | `int` | The most rounds the loop will run. A cost cap, not a target; defaults to `3`. |

```python
loop = sf.CorrectiveLoop(
    ["openrouter/deepseek/deepseek-v4-pro", "openrouter/qwen/qwen3.8-2.4t-a95b", "openrouter/z-ai/glm-5.2"],
    judge="openrouter/moonshotai/kimi-k3",
    max_rounds=3,
)
report = sf.evaluate(loop, benchmark="ifeval", limit=1)
```

### SelfCorrective

The solo shape: one model drafts under the same check and writes its own retry feedback from the check's sanitized violations: the coaching role the panel gives to a separate judge, played by the only model present.

```python
sf.SelfCorrective(
    model: str | Recipe,
    *,
    max_rounds: int = 3,
    name: str | None = None,
)
```

| Attribute | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | The recipe's name. Taken from the member unless you pass one. |
| `member` | `Recipe` | The single model that drafts and coaches itself between rounds. |
| `max_rounds` | `int` | The most rounds it will run. A cost cap, not a target; defaults to `3`. |

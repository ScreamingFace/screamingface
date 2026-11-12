# Reproduce & share (url4)

Source: https://docs.screamingface.ai/sf-client/guides/reproduce-and-share

Read the exact plan a run executed, and hand it to someone else.

Every candidate result carries a [`url4`](learn-url4.md) string: the complete plan [the engine](learn-engine.md) actually ran (your candidate, the benchmark's routes, retry prompts, and protocol revision), written as a single line of text you can read, diff, and share.

The shape is always `(sources)!intent`: inputs in parentheses, then what to do with them after the `!`. A source can itself be another url4, so the format is recursive, which is how a fusion nests inside a larger expression without special handling.

[Diagram: A url4 has the shape (sources)!intent: sources in parentheses, then an intent after the bang. A source can itself be another url4, so expressions nest.]

Every url4 is sources in parentheses, then an intent after the bang.

Here is a real one: the candidate part of the url4 of a single [Model](sf-client-guides-models.md) evaluated on MedXpert (its answer prompt trimmed to `…`). The full expression wraps it with the benchmark's routes and pinned revision:

```
(model_1:0.0:/openrouter/deepseek/deepseek-v4-flash($input)!'Answer the request accurately and completely. …', _sf_recipe:0.0:'{"recipe":{"binding":"model_1","kind":"model","name":"deepseek-v4-flash","named":false,"role":"model"},"schema":"screamingface.recipe.v1"}')!'$model_1'
```

Read it outside-in:

-   The outer `( … )!'$model_1'` is the candidate: named sources inside the parentheses, and a final intent that returns `$model_1`.
-   `model_1` is the first source: a call to the model route `/openrouter/deepseek/deepseek-v4-flash` with the case input `$input` bound, and its own intent, the answer prompt. The `0.0` after the name is its weight.
-   `_sf_recipe` is the second source: a JSON value that records the recipe's kind and names, so `to_python()` can rebuild the Python code.

A [Fusion](sf-client-guides-fusions.md) reads the same way, with more members (`model_2`, …) and a `synthesis_1` step that reads the members as `outputs` and writes the synthesis, which the final intent returns. Nothing is held back from the line: the routes, the parameters, the prompts, and the pinned protocol are all written into it. See [url4](learn-url4.md) for the full grammar and protocol.

This makes a result reproducible. A score alone is a claim. A score with its url4 shows exactly what produced it. And since the expression is also an address the engine can resolve, that same string reruns the evaluation or calls the fusion like a single model, in whatever workflow you use. See [url4](learn-url4.md) for the protocol itself.

## What you can do

-   Read the `url4` that any candidate in a report actually ran.
-   Turn a `url4` string back into editable code, then rerun or remix it.
-   See what actually ran, including defaults you never set.
-   Check which benchmark revision the run used.
-   Inspect the operation graph a candidate compiled to.
-   Serialize a whole report and pass it along.

## Main APIs

| API | What it does |
| --- | --- |
| `sf.Url4(text)` | Wrap a url4 string you were given, so a copied expression becomes the same first-class value a report hands back. |
| `Url4.to_python()` | Reconstruct editable `sf.Model` / `sf.Fanout` / `sf.Synthesize` / `sf.Pipeline` code from an expression, including the `sf.evaluate(...)` line when the url4 embeds a benchmark. Local and free. |
| `CandidateResult.url4` | The complete expression the engine ran, as a string you can read, diff, and rerun. |
| `CandidateResult.operations` | Same plan as structured data: a DAG of `sf.OperationInfo` values, each with `id`, `kind`, `label`, and `depends_on` edges. |
| `CandidateResult.run_id` | The engine's identifier for this run. |
| `Report.benchmark.revision` | The pinned protocol revision the run used, which appears inside the url4's routes. |
| `Report.to_dict()` · `Report.to_json()` | Serialise the whole report, as a dict or one JSON string, carrying schema `screamingface.report.v1`. |

## How to

### 1 · Read a url4

A url4 comes from a completed run. Each candidate in a report carries the expression that actually executed as `report.candidates[name].url4`. A Recipe on its own does not have one yet, because the benchmark's routes and pinned revision are only linked in at evaluation time. If somebody sends you an expression as plain text, wrap it in `sf.Url4()` to get the same object back.

```python
c = report.candidates.only
c.url4          # the exact expression the engine ran

# Or build one from a string somebody handed you.
sf.Url4("(candidate='…compiled url4…')!'$model_0'")
```

What you get back is the full expression in the shape annotated above: the routes, the parameters, the answer prompt, and the pinned benchmark revision. The single-Model run above produces 1,888 characters, because everything the SDK filled in on your behalf is written out explicitly, but all of it is meant to be read.

### 2 · Turn a url4 back into code

Because a `url4` is a complete plan, it converts back into the recipe that produced it. `to_python()` reconstructs the `sf.Model`, `sf.Fanout`, `sf.Synthesize`, `sf.Pipeline` and the judge, narrow and reducer steps as a chain joined with `>>`, nested as they originally were, so you can edit one part and run the result as your own next attempt. It costs nothing, since it is a local transformation rather than a run. Passing the expression to `sf.evaluate()` instead runs it again as it stands, which can spend.

```python
plan = report.candidates["frontier-trio"].url4   # or any url4 string you were given

plan.to_python()    # editable sf.Model / sf.Fanout / sf.Synthesize / sf.Pipeline code, no spend
sf.evaluate(plan)   # a new paid run of the same recipe over the same benchmark
```

The generated code compiles back to the same url4: a plain fusion and a judge chain, each run through `to_python()` and evaluated, gave the url4 they started with. A recipe with no scoring judge and no field pick has the same url4 as on 0.1.10: the single-model run above and a plain fusion (2,694 characters) are byte for byte equal. Two kinds of recipe have a new url4, so their gateway calls miss the cache once:

-   **A scoring judge:** `sf.Judge` uses the template `judge-template@2`, where the rubric alone says which way is better. A judge fusion that was 3,668 characters is 3,667.
-   **A field pick:** `sf.ArgMax("field:x")`, `sf.ArgMin("field:x")` and `sf.Rank(k, by="field:x")` read a signal. A max-field pick that was 2,771 characters is 2,725.

`to_python()` refuses a url4 written by an older SDK for these two cases:

```python
sf.Url4(url4_with_a_scoring_judge_from_0_1_10).to_python()
```

```
ValueError: URL4 Candidate has an unsupported judge call
```

```python
sf.Url4(url4_with_a_max_field_pick_from_0_1_10).to_python()
```

```
ValueError: URL4 Candidate has a pick spec this SDK version cannot rebuild
```

Build the recipe again with the current names.

### 3 · Inspect the operation graph

`operations` is the same plan as structured data: a directed acyclic graph of `OperationInfo` values, each with an `id`, a `kind`, a `label` and its `depends_on` edges.

```python
c = report.candidates.only
len(c.operations), [o.kind for o in c.operations]
```

```
(1, ['model'])
```

A solo model is one operation. A [Fusion](sf-client-guides-fusions.md) contributes one per member plus the synthesis step, so this is where you read a fusion's shape rather than inferring it from its name.

### 4 · Identify the run

```python
c.run_id
```

```
'DgvSOveXycxBS37ACT3BZI5unjRvUDwSOoxtAwhtpZPGgfZZMfnckus48WesTk82'
```

### 5 · Share the whole report

```python
report.to_dict()   # schema: screamingface.report.v1
report.to_json()   # the same, as one string
```

The dict carries a `schema` field, `screamingface.report.v1`, so a consumer can tell what shape it is reading. Every candidate's `url4`, scores, metrics, usage and the pinned benchmark revision travel with it.

## What "reproduce" means here

A url4 pins the run's **definition**. Pass it to `sf.evaluate()` and you start a new run. With the cache on, that run goes through it like any other: a call that the cache already holds is a hit and costs nothing, and the other calls are paid. The local gateway starts with the request cache on. `sf.evaluate(..., use_cache=False)` opts a run out of it, and every call is then paid. A run that bypasses the cache asks the same models the same questions under the same protocol. Models are not deterministic, so a fresh run can diverge slightly.

To check a published score, use `sf.evaluate(pinned_cache="…")` or `sf.evaluate(score_id="…")`. The Client reads the original recipe and seed from the board, runs against the pinned cache, and returns a report with the verdict on its single result's `reproduction` field. A replay that cannot start raises `sf.ReproductionError`. See the [Leaderboards guide](sf-client-guides-leaderboards.md) and the [caching page](learn-caching.md).

## Links

-   [Companion notebook: `00_quickstart.ipynb`](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb), which reads a candidate's url4 and rebuilds it

# Map-reduce for fusions

Source: https://docs.screamingface.ai/sf-client/guides/map-reduce

A fusion can dispatch a question to its member models, then map, filter and reduce what comes back into the one answer a benchmark grades. This page covers each stage and the signals that pass between them.

In ScreamingFace, every [fusion](sf-client-guides-fusions.md) can be constructed as a map-reduce pipeline. A **dispatch** stage puts the question to the member models. A **reduce** stage turns what comes back into a single answer, and that answer is what the benchmark grades. Two optional stages can sit in between: **map** attaches a number, called a **signal**, to each answer independently, and **filter** drops answers before the reducer sees them.

What varies most between fusions is the dispatch. The simplest, `sf.Fanout`, broadcasts the question to every member in parallel and hands on a **panel**: N answers, one per member. Other strategies route the question to some members, cascade through them in order, or [chain them as a pipeline](sf-client-guides-pipelines.md), and what they hand on depends on the strategy.

You write the stages left to right and join them with `>>`. A fusion starts with a dispatch (or a solo [Model](sf-client-guides-models.md)) and ends with a reducer; anything in between is optional.

[Diagram: A fusion as a chain. sf.Fanout maps the question to three members and passes on three answers. An optional mapper scores each answer. An optional selector filters to the top two. A reducer collapses them to one answer, which the benchmark grades.]

## The four stages at a glance

In the fusions on this page, every step is one of four kinds, and each kind has a fixed contract with the panel:

| Stage | Step | Panel in → out | Required | Examples |
| --- | --- | --- | --- | --- |
| Dispatch | `sf.Fanout` | question → N answers | Yes, always first | `sf.Fanout([a, b, c])` |
| Map | mapper | N → N, plus a signal on each | No | `sf.Judge` |
| Filter | selector | N → N or fewer | No | `sf.Rank`, `sf.Filter` |
| Reduce | reducer | N → 1 answer | Yes, always last | `sf.Vote`, `sf.ArgMax`, `sf.Synthesize` |

Mappers and selectors take a panel and return a panel, so you can stack them between the dispatch and the reducer.

## Dispatch: fan out to a panel

`sf.Fanout(members)` is the simplest dispatch: it broadcasts the question to every member in parallel and returns a **panel** with one answer per member. Nothing is scored or chosen yet. Members are usually `sf.Model` instances, each identified by a provider-prefixed model id (see [Models](sf-client-guides-models.md)); since fusions nest, a member can also be another fusion. The fan-out is also where you declare signals measured from each member's own response, with `signals=`, covered under Map below.

On its own, a fan-out is a valid expression but not a runnable fusion. It opens a chain that a reducer has to close:

```python
import screamingface as sf

a = sf.Model("openrouter/anthropic/claude-opus-4.8")
b = sf.Model("openrouter/openai/gpt-5.5")
c = sf.Model("openrouter/google/gemini-3.5-pro")

# Dispatch: send one question to every member, in parallel.
panel = sf.Fanout([a, b, c])
panel
```

```
Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5', 'openrouter/google/gemini-3.5-pro'])
```

## Reduce: collapse to one answer

A **reducer** reads the whole panel and returns one answer. It is **terminal**: nothing can follow it, and its output is what the benchmark grades. The simplest is `sf.Vote()`, which returns the answer most members agree on:

```python
# Reduce: collapse the panel to one answer with a rule.
agree = sf.Fanout([a, b, c]) >> sf.Vote()
agree
```

```
Fanout([...]) >> Vote()
```

That is a complete, runnable fusion. Everything after this section is optional; reach for it when plain agreement isn't enough.

### Choosing a reducer

Reducers differ in where the final answer comes from: copied verbatim from one member, computed from the members' answers, or newly written by a model. Several decide using a signal, the number covered in the next section. The [Reducers reference](sf-client-api-reducers.md) has full signatures.

| Reducer | What it returns | Final answer is |
| --- | --- | --- |
| `sf.Vote()` | The answer most members agree on. Pass `weights=` to count some answers more. | Copied from a member |
| `sf.Median()` · `sf.Mean()` | The middle, or the (weighted) average, of the members' numeric answers. | Computed, or the nearest member |
| `sf.ArgMax(by)` · `sf.ArgMin(by)` | The answer with the highest / lowest value of the signal `by`. | Copied from a member |
| `sf.Synthesize(model)` | A new answer that `model` writes after reading the panel. | Newly written |

## Map: score each answer

A **signal** is a named number on each answer: a stated confidence, a judge's score, a cost. Every answer carries a `signals` map of name to number, for example `{ "conf": 90, "cost_usd": 0.004 }`. A step names the one it wants (as `weights=`, `by=` or `where=`), and you can read them yourself with `answer.signals["name"]`. Signals come from three places:

-   **Extracted from the model's response**, declared with `signals={"name": source}` on `sf.Fanout`. Each source measures something about a member's own answer as it comes back, with no extra step in the chain:
    -   `sf.Verbalized(pattern)`: a number the model states in its text, pulled out by a regex (e.g. a `Confidence: 90` line).
    -   `sf.Logprob(...)`: how certain the model was, from the token probabilities of its answer.
    -   `sf.Consistency(n=N)`: how stable the answer is. Rerun the member N times and take the fraction that give the same answer.
-   **Scored by a judge**, an extra step that runs after the answers come back. `sf.Judge` runs a separate judge model over each answer and records its grade as `score:judge`.
-   **Recorded by the engine**, always present with nothing to declare: each call's `cost_usd`, `latency_ms`, `tokens_in` and `tokens_out`, plus any field of a JSON answer read as `field:<path>` (e.g. `field:confidence`).

The example below reads a signal as a **weight**. Each member is prompted to end with a `Confidence:` line, `sf.Verbalized` pulls that number out as `conf`, and `sf.Vote(weights="conf")` makes more confident answers count for more. Every signal has its own requirement, listed in the table that follows.

```python
# A signal read as a weight: confidence-weighted vote.
signals = {"conf": sf.Verbalized(r"Confidence: (\d+)")}
weighted = sf.Fanout([a, b, c], signals=signals) >> sf.Vote(weights="conf")
weighted
```

```
Fanout([...], signals={'conf': Verbalized('Confidence: (\\d+)')}) >> Vote(weights='conf')
```

### Available signals

| Signal | The number it yields | Requires |
| --- | --- | --- |
| `sf.Verbalized(pattern)` | A number the model wrote in its answer, extracted with a regex (e.g. `Confidence: 90`). | The prompt asks the model to write it. |
| `sf.Logprob(...)` | The answer's mean log-probability. | The provider returns logprobs. |
| `sf.Entropy(...)` | The uncertainty of the token distribution. | The provider returns logprobs. |
| `sf.Consistency(n=N)` | The fraction of N re-runs that agree. | N extra calls per member. |
| `"score:judge"` | The judge model's score for the answer. | An `sf.Judge` step earlier in the chain. |
| `"field:<path>"` | A value parsed from the answer's JSON (e.g. `field:confidence`). | The member returns that field. |
| `"cost_usd"` · `"latency_ms"` · `"tokens_in"` · `"tokens_out"` | The call's recorded cost, latency or token counts. | Nothing; always available. |

### Reading a signal

Steps refer to signals by name: pass it to `weights=` to weigh by it, or to `by=` to rank by it. To read one directly, use `sf.signal("name")`.

A missing value is not an error. If an answer lacks the signal (say a model skipped its `Confidence:` line), the value is `None` and that answer sits out the step. An unknown name is an error: a name that no earlier step provides raises before any model is called, so a typo never costs you a run.

### Signals in practice

A few canonical patterns. Each declares or reads a different signal, then lets a reducer act on it:

```python
# Keep the single most confident answer.
sf.Fanout([a, b, c], signals={"conf": sf.Verbalized(r"Confidence: (\d+)")}) >> sf.ArgMax("conf")

# Average the members' numbers, weighted by that same confidence.
sf.Fanout([a, b, c], signals={"conf": sf.Verbalized(r"Confidence: (\d+)")}) >> sf.Mean(weights="conf")

# Self-consistency: rerun each member three times, keep the most stable.
sf.Fanout([a, b], signals={"cons": sf.Consistency(n=3)}) >> sf.ArgMax("cons")

# Trust the model that was most certain, by answer log-probability.
sf.Fanout([a, b], signals={"lp": sf.Logprob("prob")}) >> sf.ArgMax("lp")

# Among the two cheapest answers, take the majority.
sf.Fanout([a, b, c]) >> sf.Rank(2, by="cost_usd", order="min") >> sf.Vote()
```

### Putting it together: a judged fusion

Dispatch, map and reduce in one chain: fan out to three models, have a cheap judge model score each answer, and keep the highest-scoring one. No selector needed.

```python
import screamingface as sf

a = sf.Model("openrouter/anthropic/claude-opus-4.8")
b = sf.Model("openrouter/openai/gpt-5.5")
c = sf.Model("openrouter/google/gemini-3.5-pro")

# dispatch → map → reduce, as one recipe.
fusion = (
    sf.Fanout([a, b, c])                                   # dispatch: three answers
    >> sf.Judge(                                           # map:      a score on each
        "openrouter/google/gemini-3.5-flash-lite",
        rubric="Score 10 if the answer is fully correct, else lower.",
    )
    >> sf.ArgMax("score:judge")                            # reduce:   keep the best-scored answer
)

report = sf.evaluate(fusion, benchmark="ifeval", limit=20)
report.score
```

Stage by stage: `sf.Fanout` **dispatches** the question to three members, `sf.Judge` **maps** a `score:judge` onto each answer, and `sf.ArgMax("score:judge")` **reduces** the panel to the best-scored answer. `sf.evaluate` then runs the fusion on 20 IFEval prompts and grades each final answer. Every stage swaps independently: change the rubric, weigh by the judge's score with `sf.Vote(weights="score:judge")` instead of taking the max, or drop the judge and rank by a declared signal. Each swap is a new fusion built from the same four kinds of step.

## Filter: drop answers before reducing

A **selector** removes answers from the panel, usually by reading a signal, so the reducer only sees the ones worth keeping. This matters most for `sf.Synthesize`, which reads every answer it's given. A selector is not terminal: a reducer still has to follow it.

-   `sf.Rank(k, by=...)` keeps the top `k` by a signal. The count is fixed: always `k`, as long as that many answers carry the signal.
-   `sf.Filter(where=...)` keeps every answer that clears a threshold. The count varies, and can be zero.
-   `sf.Concat` joins the panel's answers.

Selectors read the same signals reducers do. The `conf` signal from earlier can decide whether an answer survives, or how much it counts:

[Diagram: One signal, conf, scores answers a, b and c at 90, 60 and 75. sf.Rank(2, by=conf) reads it to keep a and c and drop b. sf.Vote(weights=conf) reads it to let all three vote, weighted 90, 60 and 75.]

One declared signal, two readers: `sf.Rank` uses it to decide which answers survive, `sf.Vote` to decide how much each one counts.

Keep the two most confident answers, then have a model write the final answer from just those two:

```python
# The same signal read to filter: keep the two most confident, then write.
best = (
    sf.Fanout([a, b, c], signals={"conf": sf.Verbalized(r"Confidence: (\d+)")})
    >> sf.Rank(2, by="conf")
    >> sf.Synthesize("openrouter/anthropic/claude-opus-4.8")
)
best
```

```
Fanout([...], signals={'conf': Verbalized('Confidence: (\\d+)')}) >> Rank(2, by='conf') >> Synthesize('openrouter/anthropic/claude-opus-4.8')
```

The same move extends the judged fusion: rank by the judge's score, keep the top two, and swap `sf.ArgMax` for `sf.Synthesize` so a model writes the final answer from the two best-scored drafts.

```python
# Add a selector to keep the top two before a writer synthesizes.
fusion = (
    sf.Fanout([a, b, c])
    >> sf.Judge(
        "openrouter/google/gemini-3.5-flash-lite",
        rubric="Score 10 if the answer is fully correct, else lower.",
    )
    >> sf.Rank(2, by="score:judge")                        # filter: keep the top two
    >> sf.Synthesize("openrouter/anthropic/claude-opus-4.8")  # reduce: write from just those two
)
```

## Other ways to dispatch

`sf.Fanout` is the simplest dispatch: every member answers every question. Routers, cascades and pipelines are dispatch strategies too. They add **control flow**, deciding *which* members run and in what order, often by reading the same signals you have seen here. `sf.Gate` is the first control-flow piece: it reads a signal and decides whether to answer or abstain. What each strategy hands to the stages after it depends on the strategy; this page covers what follows a fan-out.

## See also

-   [Fusions](sf-client-guides-fusions.md): the fan-out and `sf.Synthesize` in depth.
-   [Pipelines](sf-client-guides-pipelines.md): chaining steps and nesting recipes.
-   [Reducers reference](sf-client-api-reducers.md): signatures for every reducer, selector, judge and signal.

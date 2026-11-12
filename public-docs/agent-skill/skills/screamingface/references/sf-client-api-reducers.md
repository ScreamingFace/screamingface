# Reducers

Source: https://docs.screamingface.ai/sf-client/api/reducers

The steps of a fan-out block: reducers, judges, narrow steps, a gate and declared signals.

A fusion is a chain of steps joined with `>>`. `sf.Fanout` sends the question to every member. The block ends in one **reducer**, a step the engine runs without writing a new answer, or in one `sf.Synthesize` writer, which is a model. A reducer reads each member's answer, picks or builds the result, and compiles to one combine call in the candidate's [url4](sf-client-api-url4.md). The [Fusions](sf-client-api-fusions.md) reference covers `sf.Fanout` and `sf.Synthesize`.

Note: Reducers need an engine that serves the combine operators, and a narrow step before a reducer needs an engine with the narrow step. An engine without them raises `sf.EngineCapabilityError` (code `engine_capability_missing`) before anything is spent.

```python
a = sf.Model("openrouter/deepseek/deepseek-v4-flash", name="a")
b = sf.Model("openrouter/google/gemini-3.5-flash-lite", name="b")
c = sf.Model("openrouter/anthropic/claude-haiku-4.5", name="c")

fusion = sf.Fanout([a, b, c]) >> sf.Vote()
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
```

## The steps of a block

| Role | Steps |
| --- | --- |
| Map | `sf.Fanout`: sends the input to every member and opens the block. It declares the signals that later steps read. |
| Score | `sf.Judge`: one judge call scores every member. The score is the signal `score:judge`. |
| Narrow | `sf.Rank`, `sf.Filter` and `sf.Concat`: keep some members, or join them, for the step that follows. |
| End | `sf.Vote`, `sf.Median`, `sf.Mean`, `sf.ArgMax`, `sf.ArgMin`, `sf.First`, `sf.Merge`, `sf.JudgePick`, `sf.Gate` or `sf.Synthesize`. |

The chain checks these rules, and each one raises `ValueError`:

| Rule | Message | Raised |
| --- | --- | --- |
| A block ends in one reducer or one `sf.Synthesize`. | `the chain ends inside a sf.Fanout block: add a reducer or sf.Synthesize` | When you compile or evaluate |
| A block has at most one judge. | `a block takes one judge: sf.Judge and sf.JudgePick use the same judge signal` | When you build the chain |
| A `sf.Judge` needs a step that reads `score:judge`. | `sf.Judge scores the members, but no step reads score:judge` | When you build the chain |
| A block has at most 4 narrow steps. | `a block takes at most 4 narrow steps` | When you build the chain |
| `sf.Concat` is followed by `sf.Synthesize`. | `sf.Concat must be followed by sf.Synthesize` | When you build the chain |
| A step reads only a signal that the `sf.Fanout` declares. | `a step reads sf.signal('nope'), which this sf.Fanout does not declare (declared: none)` | When you build the chain |

## Reducers that end a block

| Reducer | What it returns |
| --- | --- |
| `sf.Vote(*, over="last_line", normalize="text", weights=None)` | The first member, in author order, that holds the most common answer, as that member's text unchanged. `over` is a rule name, `"field:<path>"` or an `sf.Extract(...)`. `weights` is a list with one positive number per member, or a signal key such as `"conf"`. A member with no usable value does not vote. |
| `sf.Median(*, over="last_number", select="nearest", weights=None)` | The median of the members' numeric answers: the nearest member's text (`select="nearest"`), or the number itself (`select="value"`). `weights` takes the same values as for `sf.Vote`. With weights, the answer is the first value where the running weight reaches half the total, or the mean of that value and the next at exactly half. A member with a missing or non-positive weight is dropped and is never the nearest member. Any other `select` raises `ValueError: sf.Median select must be 'nearest' or 'value'`. |
| `sf.Mean(*, over="last_number", select="value", weights=None)` | The mean of the members' numeric answers: the number (`select="value"`), or the text of the member nearest the mean (`select="nearest"`), where a tie goes to the first member in author order. `weights` takes one positive number per member, or a signal key. A member with a missing, zero, negative or non-number weight is dropped. The sums are exact and the one division is rounded to 34 significant digits. Give every member the same scale for a confidence weight: the engine cannot tell that one member writes `80` and another `0.8`. |
| `sf.ArgMax(by, *, output=None)` | The member with the highest value of one signal, as that member's text unchanged. `by` is a signal key: `cost_usd`, `latency_ms`, `tokens_in`, `tokens_out`, `score:judge`, `field:<path>` or a signal the fan-out declares. A member whose field is missing or is not a number is left out with the reason `no_signal`. With `output="answer"`, the answer is that top-level field of the winner's JSON reply instead: a string as it is, any other value as canonical JSON. When the field is missing, `null` or blank, or the reply is not a JSON object, the case abstains with the reason `output_missing`, and the next member is never used. |
| `sf.ArgMin(by, *, output=None)` | The member with the lowest value of one signal, with the same keys and `output=` as `sf.ArgMax`. A tie goes to the first member in author order. A judge rubric such as an error count reads as lower is better with `sf.Judge(...) >> sf.ArgMin("score:judge")`. |
| `sf.First(*, where, output=None)` | The first member, in author order, whose JSON field equals a value: `sf.First(where=sf.field("answer") == "yes")`. `sf.field(path, normalize=None)` names the field. `output=` works as for `sf.ArgMax`. |
| `sf.Merge(fields)` | One JSON object with exactly the declared fields. `fields` maps each name to a `sf.FieldRule`. A member that is not a JSON object is skipped. |
| `sf.JudgePick(model, *, rubric, params=None)` | A judge model names one member, and the answer is that member's text unchanged. A reply that is not valid fails the case with `judge_reply_invalid`. Members reach the judge in author order, so a judge can favour a position. |
| `sf.Gate(*, when, then, otherwise="abstain", abstain_if=None)` | Keeps the answer of `then` when `when` holds. See [Gate](#gate). |

`sf.FieldRule` is built with a constructor method, never directly: `FieldRule.majority(normalize=None)`, `FieldRule.max()`, `FieldRule.union(normalize=None)`, `FieldRule.from_member(position)` (1-based author position), and `FieldRule.model(model, *, prompt, params=None)`, where a model writes the field from that field's values only.

Three members that answer 1, 2 and 6, combined by a mean weighted `[1, 1, 2]`, give (1 + 2 + 12) / 4:

```python
def number(n, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f"Ignore the question. Reply with exactly the number {n} and nothing else.",
    )

a, b, c = number(1, "a"), number(2, "b"), number(6, "c")
fusion = sf.Fanout([a, b, c]) >> sf.Mean(weights=[1, 1, 2])
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
report.candidates.only.cases[0].output
```

```
'3.75'
```

The same three members under `sf.Median()` return the nearest member's text:

```python
fusion = sf.Fanout([a, b, c]) >> sf.Median()
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
report.candidates.only.cases[0].output
```

```
'2'
```

With members that reply in JSON, `sf.ArgMax` with `output="answer"` returns one field of the winner's reply:

```python
def reply(answer, confidence, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f'Ignore the question. Reply with exactly this JSON: {{"answer": "{answer}", "confidence": {confidence}}}',
    )

members = [reply("red", 0.2, "a"), reply("green", 0.9, "b"), reply("blue", 0.5, "c")]
fusion = sf.Fanout(members) >> sf.ArgMax("field:confidence", output="answer")
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
report.candidates.only.cases[0].output
```

```
'green'
```

## Judges

| Step | What it does |
| --- | --- |
| `sf.Judge(model, *, rubric, params=None)` | Scores every member with one judge call. The judge replies with one JSON object with one finite score per member, and a later step reads the scores as `score:judge`: `sf.ArgMax("score:judge")`, `sf.ArgMin("score:judge")`, `sf.Rank(k, by="score:judge")`, `sf.Filter(where=sf.signal("score:judge") >= x)` or a weight `sf.Vote(weights="score:judge")`. The rubric says which way is better. |
| `sf.JudgePick(model, *, rubric, params=None)` | A reducer: the judge names one member. |

```python
judge = sf.JudgePick(
    "openrouter/google/gemini-3.5-flash-lite",
    rubric="Pick the answer that follows every instruction.",
)
fusion = sf.Fanout([a, b]) >> judge
```

```python
fusion = (
    sf.Fanout([a, b])
    >> sf.Judge("openrouter/google/gemini-3.5-flash-lite", rubric="Score 10 if the answer is 2, else 1.")
    >> sf.ArgMax("score:judge")
)
```

A `sf.Judge` scores call uses the template `judge-template@2`, with `input=panel` when the fan-out has a quorum. `sf.JudgePick` keeps `judge-template@1 returns=label`. When a judge and the writer after it use the same model, the SDK warns with `sf.JudgeWriterWarning`.

## Narrow steps

A narrow step keeps some members. It comes before a reducer in the same combine call, or before an `sf.Synthesize` writer, and a narrow step never ends a recipe. At most 4 narrow steps fit in a block. A member that a narrow step leaves out is excluded with the reason `not_selected`.

[Diagram: Flow: three members answer 1, 1 and 2; a Judge scores them 10, 10 and 2; Rank keeps the two best, a and b; the Vote reads a and b and answers 1; member c is excluded with the reason not_selected.]

One combine call with a Judge, a Rank and a Vote: the Vote reads only the kept members.

| Step | What it keeps |
| --- | --- |
| `sf.Rank(k, *, by, order="max")` | The `k` members with the highest (`order="max"`) or lowest value of the signal `by`, best first. `k` is 1 to 256: `sf.Rank(0, ...)` raises `ValueError: sf.Rank k must be between 1 and 256`. A member with no value for the signal is left out with the reason `no_signal`. |
| `sf.Filter(*, where, over=None)` | The members that pass `where`, in author order: `sf.matches(pattern)`, or a comparison on a signal such as `sf.signal("field:x") >= 0.6`. `over=` reads the text for `sf.matches`, and a comparison on a signal with `over=` raises `ValueError`. |
| `sf.Concat(separator="\n\n---\n\n", *, label=True)` | Every member's text in author order, joined with visible boundaries, for the `sf.Synthesize` that must follow. It makes no model call. |

The `sf.Synthesize` writer after a `sf.Rank` or `sf.Filter` receives one JSON object. Its `input` key holds the Case input, and its `selected` key holds the kept members as a list of `{"id": ..., "text": ...}`, best first for a Rank and in author order for a Filter. When nothing is kept, `selected` is `[]`.

[Diagram: Flow: the Case input goes to the members, their answers go to Rank or Filter, and the writer receives the Case input and the kept members as one JSON object.]

What the writer after Rank or Filter receives: the Case input, and the kept members as a list of id and text.

```python
# a narrow step keeps some members for the writer that follows
ranked = (
    sf.Fanout([a, b, c])
    >> sf.Rank(2, by="cost_usd", order="min")
    >> sf.Synthesize("openrouter/deepseek/deepseek-v4-flash")
)
```

## Gate

`sf.Gate(when=..., then=sf.Vote(...), otherwise=..., abstain_if=...)` keeps the majority answer only when a condition holds. `then` takes `sf.Vote` only: any other step raises `TypeError: sf.Gate then= takes sf.Vote until E4c`. `when` compares one reference with a number. The references are `sf.agreement()`, the share of the members that hold the vote's answer, from 0 to 1, and `sf.signal(name).chosen()` and `sf.signal(name).mean()` for a signal that the fan-out declares: the chosen member's value and the members' mean. A reference to a key such as `cost_usd` raises `ValueError: sf.signal('cost_usd').chosen() reads a declared signal`. `>=` keeps the majority at equality. `otherwise` is `"abstain"`, `sf.JudgePick(...)` or `sf.Synthesize(...)`. `abstain_if=ref.between(lo, hi)` abstains inside a band.

Three members answer 1, 1 and 2. The vote holds 2 of 3, so `agreement()` is 0.667. A threshold of 0.7 is not met, and the case abstains with the reason `gate_not_met`:

```python
def number(n, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f"Ignore the question. Reply with exactly the number {n} and nothing else.",
    )

members = [number(1, "a"), number(1, "b"), number(2, "c")]   # the vote is 2 of 3
gated = sf.Fanout(members) >> sf.Gate(
    when=sf.agreement() >= 0.7, then=sf.Vote(), otherwise="abstain"
)
report = sf.evaluate(gated, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
case.abstained, [(a.member_id, a.status, a.reason) for a in case.answers()][-1]
```

```
(True, (None, 'abstain', 'gate_not_met'))
```

```python
sf.Gate(when=sf.agreement() >= 0.6, then=sf.Vote(), otherwise="abstain")
# the same three members: case.output is '1'
```

## Declared signals

A fan-out declares a named number for each member in `signals=`. A later step reads it by name: `sf.Vote(weights="conf")`, `sf.ArgMax("cons")`, `sf.Rank(2, by="lp")`. A signal key that the fan-out does not declare raises `ValueError` when you build the chain. `sf.Synthesize` right after `sf.Fanout` reads no signal, so that block refuses `signals=`.

| Signal | The value of each member |
| --- | --- |
| `sf.Verbalized(pattern, *, ignore_case=False)` | A number that the member states in its text: the first group of the regular expression, for example `sf.Verbalized(r"Confidence: (\d+)")`. |
| `sf.Logprob(form)` | The token log-probability of the reply: `"mean"`, `"sum"` or `"prob"`. OpenRouter models only. |
| `sf.Entropy(*, top_logprobs=5)` | The mean token entropy of the reply, in nats. OpenRouter models only. |
| `sf.Consistency(n, *, temperature=1.0)` | The share of `n` more answers, at distinct fixed seeds and the stated temperature, that agree with the member's answer. Each member answers `n` more times, so the run makes `n` more model calls per member. |
| `sf.Sum(coefficients)` | A fixed linear sum of other declared signals of the same fan-out: `sf.Sum({"x": 0.5, "y": 0.3})` gives `0.5 × x + 0.3 × y`. Each component is another declared name and not another sum. An undeclared name raises `ValueError: sf.Sum 's' adds 'x', which this sf.Fanout does not declare`. |
| `sf.signal(key)` | A reference to a signal on a member's answer. Keys: `cost_usd`, `latency_ms`, `tokens_in`, `tokens_out`, `score:judge`, `field:<path>` and the declared names. A missing value is `None`. A `by=` or `weights=` takes the key as a string. |

A vote weighted by the confidence that each member states. The member that answers `x` at 90 outweighs the two that answer `y` at 20 and 30:

```python
def stated(answer, confidence, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f"Ignore the question. Reply with exactly: Answer: {answer}  Confidence: {confidence}",
    )

fusion = sf.Fanout(
    [stated("x", 90, "a"), stated("y", 20, "b"), stated("y", 30, "c")],
    signals={"conf": sf.Verbalized(r"Confidence: (\d+)")},
) >> sf.Vote(weights="conf")
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
case.output, [a.signals["conf"] for a in case.answers()[:3]]
```

```
('Answer: x  Confidence: 90', [90.0, 20.0, 30.0])
```

A sum of two declared signals, with the value that each member got:

```python
signals = {
    "x": sf.Verbalized(r"x: (\d+)"),
    "y": sf.Verbalized(r"y: (\d+)"),
    "s": sf.Sum({"x": 0.5, "y": 0.3}),
}
fusion = sf.Fanout([a, b], signals=signals) >> sf.ArgMax("s")
```

```
member 1: {'s': 2.3, 'x': 4.0, 'y': 1.0}
member 2: {'s': 3.1999999999999997, 'x': 1.0, 'y': 9.0}
```

`sf.Consistency(n=3)` with two members makes 8 model calls: 2 answers and 3 more for each member.

```python
fusion = sf.Fanout([a, b], signals={"cons": sf.Consistency(n=3)}) >> sf.ArgMax("cons")
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
len([e for e in case.trace() if e.kind == "model_call"]), [a.signals["cons"] for a in case.answers()[:2]]
```

```
(8, [1.0, 1.0])
```

`sf.Logprob` and `sf.Entropy` need a model whose endpoint returns log-probabilities. On `gemini-3.5-flash-lite` and `gpt-5.5` through OpenRouter, the run fails with the code `logprobs_unsupported`. On `deepseek-v4-flash`, `qwen3.8-2.4t-a95b`, `gpt-oss-120b` and `llama-4-maverick`, each member is excluded with the reason `no_signal`, and the case abstains with `no_votes`. No model that was tried returned a value, so no printed value is shown for these two signals.

```python
sf.Fanout([a, b], signals={"lp": sf.Logprob("prob")}) >> sf.ArgMax("lp")
```

```
failure code: logprobs_unsupported
(a member's answers: no usable value, reason no_signal, when the provider returns no log-probabilities)
```

## Extractors and predicates

| Name | What it is |
| --- | --- |
| `sf.Extract(rule, normalize=None, **args)` | How a member's answer is read. Rules: `boxed`, `last_number`, `field`, `regex`, `last_line`, `whole`, `json`, `benchmark`, `inspect_number`, `inspect_aime`. Normalizers: `numeric`, `text`, `set`, `inspect_numeric`, `identity`. A rule name, `"field:<path>"` or `sf.Extract(...)` goes in `over=`. |
| `sf.matches(pattern, *, ignore_case=False)` | A filter predicate: the member's text matches the regular expression. A pattern the engine would refuse raises `ValueError` before any spend. |
| `sf.samples(model, n, *, seeds=None, temperature=None, prompts=None, params=None)` | `n` Models of one route that differ in an integer `seed`, so a vote counts `n` real answers. A route whose provider rejects `seed` fails before the run starts. |

## Reading what a reducer decided

`CaseResult.answers()` returns one `sf.Answer` per member in author order, then the computed answer of the step. An `Answer` has `member_id`, `text` (the member's original output, or `None` when it cannot be attributed), `raw`, `value`, `status` (`answered`, `abstain`, `excluded` or `fail`), `reason` and `signals`. A computed answer has no `member_id` unless a step chose one.

```python
case = report.candidates.only.cases[0]
[(a.member_id, a.status, a.reason) for a in case.answers()]
```

```
[('member_1', 'answered', None),
 ('member_2', 'answered', None),
 ('member_3', 'answered', None),
 ('member_1', 'answered', None)]
```

When no member gives a usable value, the case **abstains**: its output is `''`, its score is `0.0`, and `case.abstained` is `True`. It does not fail, and `report.ok` stays `True`. `CandidateResult.abstained_count` counts them. The reasons seen in these runs are `no_votes`, `gate_not_met`, `output_missing`, `no_signal` and `missing`.

```python
fusion = sf.Fanout([a, b]) >> sf.Vote(over="boxed")
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
case.abstained, case.output, report.candidates.only.score
```

```
(True, '', 0.0)
```

`CaseResult.trace()` returns the steps in operation order as `TraceEntry` values of kind `model_call`, `extract` and `reduce`. [CandidateResult](sf-client-api-candidate-result.md) covers the combine evidence of each step.

```python
[e.kind for e in case.trace()]
['model_call', 'model_call', 'model_call', 'extract', 'extract', 'extract', 'reduce']
```

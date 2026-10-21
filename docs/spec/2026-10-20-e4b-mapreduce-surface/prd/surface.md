# PRD: the public surface (P0)

Spec: [00-overview.md](../00-overview.md). This PRD gives every public name of the new surface, its
signature, its rules and its refusals. [lowering.md](lowering.md) says what each one compiles to.

## 1. Step categories

Every value that can be in a chain has one category.

| Category | Values | Ends a block? |
|---|---|---|
| recipe | `sf.Model`, `sf.Pipeline`, `sf.CorrectiveLoop`, `sf.SelfCorrective` | (not in a block) |
| map | `sf.Fanout` | no (opens a block) |
| score | `sf.Judge` | no |
| narrow | `sf.Rank`, `sf.Filter`, `sf.Concat` | no |
| reduce | `sf.Vote`, `sf.Median`, `sf.Mean`, `sf.ArgMax`, `sf.ArgMin`, `sf.First`, `sf.Merge`, `sf.JudgePick`, `sf.Gate` | yes |
| write | `sf.Synthesize` | yes |

A **block** is `Fanout`, then at most one `Judge`, then 0–4 narrow steps, then one reduce or write
step. A **chain** is a sequence of `sf.Model` stages, nested `sf.Pipeline` values and closed
blocks. A closed block, or a chain, is a recipe: it can be a `Fanout` member, a `Pipeline` stage, a
`CorrectiveLoop` member or a `Synthesize` model.

`sf.CorrectiveLoop` and `sf.SelfCorrective` stay **root** recipes, as today: they are not a chain
stage and not a `Fanout` member (`S/recipe.py:83-84`, `:122-127`). `CH-13` putting one in a chain
or a `Fanout` is refused with today's message.

**Staging.** Until the swap (unit 7) these names live in the private package
`screamingface._surface` and only new tests import them. At the swap they become `sf.*`.

## 2. The chain

### 2.1 `>>` and `sf.Pipeline`

- `a >> b` returns `sf.Pipeline([a, b])`. Every step class and every recipe class has `__rshift__`.
  A route string on the left works through `__rrshift__`: `"openai/gpt-4o" >> sf.Model(...)` is
  `sf.Pipeline([sf.Model("openai/gpt-4o"), sf.Model(...)])`. **Erratum E1:** before the swap only
  `_surface` values chain; `__rshift__` on `sf.Model` and today's `sf.Pipeline` (and so the route
  string on the left of a `Model`) comes at the swap (unit 7).
- `sf.Pipeline(steps, *, name=None, optional=False)` is the explicit form. `steps` is a sequence of
  route strings and step values. An unnamed nested `Pipeline` is flattened (the rule of today,
  `S/pipeline.py:65-78`). A named `Pipeline` keeps its grouping.
- `CH-14` A named `sf.Pipeline` must not end in an open block: "a named sf.Pipeline groups its
  stages, so close the sf.Fanout block inside it". (A later `>>` cannot reach into a named group.)
- `>>` is read left to right: `a >> b >> c` is `(a >> b) >> c`. A right-hand group that is not a
  valid chain alone raises when it is built: `a >> (sf.Rank(...) >> sf.Vote())` raises `CH-1` at
  `sf.Rank(...) >> sf.Vote()`. There is no associativity claim.
- `Recipe.then` is deleted (O2).
- The inferred name of a chain joins the names of its stages with `->` (today's rule).
- `.name` of a closed block is the name of its lowered value, because that name goes into the
  topology bytes (`S/_evaluation/topology.py:335-347`): the `Fanout` name for a block that lowers
  to one Fusion, and `"<fanout name>-><writer name>"` for a block that lowers to
  `Pipeline([Fusion, writer])` (lowering §2.2).

### 2.2 Chain rules (checked at construction)

The chain is read left to right with these states. `CH-n` is the rule id that the tests cite.

| State | Next step allowed | Next state | Refusal for anything else |
|---|---|---|---|
| `OUT` (start, or after a recipe or a closed block) | recipe | `OUT` | `CH-1` a score, narrow, reduce or write step: "sf.{X} needs a sf.Fanout before it" |
| | `Fanout` | `MAP` | |
| `MAP` (after `Fanout`) | `Judge` | `SCORED` | `CH-2` a recipe or a `Fanout`: "a sf.Fanout block needs a reducer or sf.Synthesize before the next stage" |
| | narrow | `NARROW` | |
| | reduce, write | `OUT` (closed) | |
| `SCORED` (after `Judge`) | narrow | `NARROW` | `CH-3` a second `Judge`, or a `JudgePick` terminal: "a block takes one judge: sf.Judge and sf.JudgePick use the same judge signal" (O9, `S/reducer.py:61`, `S/judge.py:190-196`); `CH-2` as above |
| | reduce, write | `OUT` (closed) | |
| `NARROW` (after a narrow step) | narrow (at most 4 in total) | `NARROW` | `CH-4` a fifth narrow step: "a block takes at most 4 narrow steps" (O10) |
| | reduce, write | `OUT` (closed) | `CH-5` a recipe or a `Fanout`: "a selection goes to sf.Synthesize, a reducer, or another narrow step" (O8) |
| | | | `CH-6` a `Judge`: "sf.Judge comes right after sf.Fanout" |
| after `Concat` | write | `OUT` (closed) | `CH-7` anything else: "sf.Concat must be followed by sf.Synthesize" |

- `CH-8` A chain whose last block is open (state `MAP`, `SCORED` or `NARROW` at the end) is a valid
  value, so `>>` can build it step by step. Compile, `sf.evaluate` and url4 render refuse it before
  any spend: "the chain ends inside a sf.Fanout block: add a reducer or sf.Synthesize".
- `CH-9` When a block closes, the SDK builds its internal node ([lowering.md](lowering.md) §2). Every
  rule of today's `sf.Fusion` constructor runs then: the members rule, the quorum rule, the declared
  signals rules (`S/fusion.py:120-160`), the logprob member rules (`:247-310`), the consistency
  rules (`:320-380`). So a bad signal or a bad member raises at the `>>` that closes the block.
- `CH-10` A `Judge` that no later step of its block reads (§4) is refused at block close: "sf.Judge
  scores the members, but no step reads score:judge" (O9). The readers are listed in §4; a
  `Gate(then=sf.Vote(weights="score:judge"))` is a reader too. A step that reads `score:judge` with
  no `Judge` in its block is refused: "score:judge needs sf.Judge(...) after sf.Fanout". A
  `Gate(otherwise=sf.JudgePick(...))` uses its own fallback signal (`S/gate.py:92-99`), so it can be
  in a block with a `Judge`.
- `CH-11` A step value that is not a recipe (a `Judge`, a reducer, a narrow step) is refused as a
  `Fanout` member, a `CorrectiveLoop` member, a `CorrectiveLoop(judge=)` or a `Synthesize` model:
  "sf.{X} is a step, not a recipe: put it after a sf.Fanout".
- `CH-12` (**removed in unit 5**) Before unit 5 (narrow compile), a block that needs the spec `narrow` key was refused: a
  narrow step before a reducer, or two or more narrow steps before `Synthesize`. The message is
  "narrow before a reducer is not built yet". Unit 5 removes this refusal.
- `NR-C1` (O11) A narrow step before `sf.Merge`, before `sf.JudgePick`, or before a `sf.Gate` whose
  `otherwise` is not `"abstain"` is refused: "sf.{X} makes its own call over every member, so it
  cannot follow a narrow step". The `Merge` and `JudgePick` parts are tested in unit 3, the `Gate`
  part in unit 4. These steps read the whole Fusion context
  (`S/fields.py:387`, `E/combine/endpoint.py:740-772`).

## 3. Map: `sf.Fanout`

```python
sf.Fanout(members, *, signals=None, quorum="all", name=None, prompt=None)
```

- `members`: a non-empty sequence of route strings and recipes (§1). A route string becomes
  `sf.Model(route)`. The rules of `S/fusion.py:407-413` apply.
- `signals`: a mapping from a declared name to a source (`sf.Verbalized`, `sf.Logprob`,
  `sf.Entropy`, `sf.Sum`, `sf.Consistency`). The name rules and limits of parts 3, 6 and 7 apply
  unchanged (at most 8 names, one `Entropy`, one `Consistency`, the reserved prefixes).
- `quorum`: `"all"` or an int from 0 to the member count (`S/fusion.py:385-392`).
- `name`: the block name. The default joins the member names with `+` (today's Fusion rule).
- `prompt` (O6): a string. It becomes the prompt of each member that is a route string or a
  `sf.Model` with `prompt=None`. `FA-1` a member `sf.Model` that has its own prompt, or a member
  that is not a `sf.Model` or a route, is refused when `prompt=` is set: "Fanout prompt= sets the
  member prompts: member {i} already has one" / "... member {i} is not a model".
- `FA-2` `signals=` on a block whose terminal is `sf.Synthesize` with no narrow step is refused
  (today's rule `S/fusion.py:124-128`: nothing reads them).
- A `Fanout` alone is not a recipe (`CH-8`).
- `optional=` is not on `Fanout` (D10). For an optional block, write
  `sf.Pipeline([sf.Fanout(m), sf.Vote()], optional=True)`. The lowering gives that flag to the
  internal node ([lowering.md](lowering.md) §2.3).

## 3b. The `sf.Fusion` shortcut (A4, revised 2026-10-20)

```python
sf.Fusion(members, *, synthesizer, signals=None, quorum="all", name=None, prompt=None, optional=False)
```

A **function** (not a class; no second compile path) in `S/_surface/fusion.py`. It returns the
chain `sf.Fanout(members, signals=signals, quorum=quorum, name=name, prompt=prompt) >> S`:

- a reduce step (`Vote`, `Median`, `Mean`, `ArgMax`, `ArgMin`, `First`, `Merge`, `JudgePick`,
  `Gate`) or an `sf.Synthesize(...)`: `S` is the step as it is;
- a route string, an `sf.Model` or a recipe (a Pipeline or a chain): `S = sf.Synthesize(it)`;
- a narrow step (`Rank`, `Filter`, `Concat`): `S` is the step as it is, and the result is an
  **open** chain that the user closes with `>> sf.Synthesize(...)` (CH-8 at compile if not);
- an `sf.Judge(...)` is refused: "sf.Fusion synthesizer= takes a reducer, a writer or a narrow
  step; sf.Judge only scores: use sf.Fanout(...) >> sf.Judge(...) >> <reader>";
- `optional=True` gives `sf.Pipeline([<that chain>], optional=True)` (LO-5). It needs a closed
  block: with a narrow step it raises at the call, "sf.Fusion optional=True needs a closed block:
  give a reducer or a writer as synthesizer=, or close the chain first" (7e review, 2026-10-20: an
  optional open chain can never close).

The value is the ordinary chain, so `==`, `repr`, the cards and `to_python()` show the canonical
`sf.Fanout(...) >> ...` form. `isinstance(x, sf.Fusion)` is not supported (a function). Bytes:
`sf.Fusion(m, synthesizer=R)` compiles to the bytes of `sf.Fanout(m) >> R`, which equal today's
Fusion for the parity set (`ST/test_fusion_shortcut.py`). The internal node keeps its name
`FusionNode`.

## 4. Score: `sf.Judge`

```python
sf.Judge(model, *, rubric, params=None)
```

- One judge call scores every member of the block (`score:judge`). It does not pick.
- `model`: a route string. `rubric`: a non-empty string. `params`: as today (`S/judge.py:161-169`).
- `returns=` and `order=` are deleted. The scores prompt uses the neutral template
  `judge-template@2` (D2, [lowering.md](lowering.md) §4). The rubric says what a high number means.
- Readers: `Rank(by="score:judge")`, `Filter(where=sf.signal("score:judge") <op> x)`,
  `ArgMax("score:judge")`, `ArgMin("score:judge")`, `Vote(weights="score:judge")`. More than one
  reader in a block is allowed; they share the one judge call.
- `JU-1` `Median`/`Mean(weights="score:judge")` is refused (today's rule).
- `JU-2` `ArgMax`/`ArgMin("score:judge", output=...)` is refused: "output= reads a member field;
  a judge pick returns the member text".

## 5. Narrow steps

### `sf.Rank`

```python
sf.Rank(k, *, by, order="max")
```

- Keeps the `k` members with the highest (`order="max"`) or lowest (`order="min"`) value of `by`.
- `k`: int from 1 to 256. `by`: a signal key string or `sf.signal(key)` (§9). `order`: `"max"` or
  `"min"`.
- `RA-1` `by=` must be one signal. `by=sf.Judge(...)`, `by_field=` and `by_signal=` are gone.
- `Rank(by="score:judge", order="min")` is now valid (D2).
- A member with no value for `by` is excluded (`no_signal`, part 2). Fewer than `k` scored members
  abstains with `cut_not_met` (today).

### `sf.Filter`

```python
sf.Filter(*, where, over=None)
```

- `where`: `sf.signal(key) <op> x` (`>`, `>=`, `<`, `<=`, `==`) or `sf.matches(pattern)`.
- `over`: an extractor (§8). Only with `sf.matches`: the regex reads the extracted text. `FI-1`
  `over=` with a signal comparison is refused. Erratum U3a: `Filter(over=)` refuses a pinned rule
  name (`"last_line@1"`), because the filter's extract is a block extract that never pins a version
  (D-13).
- `judge=` and `extract=` are deleted. A `score:judge` comparison needs a `Judge` in the block
  (`CH-10`).

### `sf.Concat`

```python
sf.Concat(separator="\n\n---\n\n", *, label=True)
```

- Unchanged rules (`S/selection.py:214-262`). It is a narrow step that only `sf.Synthesize` can
  follow (`CH-7`).

## 6. Reduce steps

| Step | Signature | Notes |
|---|---|---|
| `sf.Vote` | `(*, over="last_line", normalize="text", weights=None, verify=None)` | `over=` replaces `extract=`. `weights`: a tuple of numbers (one per member), a signal key string or `sf.signal`. `judge=` and `gate=` are gone (`Judge` step; `sf.Gate(then=Vote())`). `verify=` takes only `None` (part 5 Q4). |
| `sf.Median` | `(*, over="last_number", select="nearest", weights=None)` | `over=` replaces `extract=`. Other rules unchanged. |
| `sf.Mean` | `(*, over="last_number", select="value", weights=None)` | As `Median`. |
| `sf.ArgMax` | `(by, *, output=None)` | The member with the highest `by`, its text copied. `output=`: one top-level JSON field of the winner (part 1). |
| `sf.ArgMin` | `(by, *, output=None)` | As `ArgMax`, lowest value. |
| `sf.First` | `(*, where, output=None)` | The first member, in author order, whose JSON field equals a value (D3). `where`: `sf.field(path, normalize=None) == value`. `normalize`: `None`, `"text"` or `"numeric"`, with today's `Pick(equals=)` rules unchanged (`S/fields.py:430-500`): with `None` the value compares as JSON text, so `== 7` also matches the string `"7"` (README:626). |
| `sf.Merge` | `(fields)` with `sf.FieldRule` values | Unchanged. |
| `sf.JudgePick` | `(model, *, rubric, params=None)` | A judge model names one member (today `Judge(returns="label")`), template `judge-template@1 returns=label`. |
| `sf.Gate` | `(*, when, then, otherwise="abstain", abstain_if=None)` | §7. |

- `sf.Pick` is deleted. `Pick(field, order=)` → `ArgMax/ArgMin("field:<field>")`.
  `Pick(by_signal=s, order=)` → `ArgMax/ArgMin(s)`. `Pick(field, equals=)` → `First(where=...)`.
- `RE-1` `ArgMax`/`ArgMin`/`Rank` with a `field:<path>` key read the field as a number signal. A
  non-number value is missing, so the member is excluded (D3).

## 7. `sf.Gate`

```python
sf.Gate(*, when, then, otherwise="abstain", abstain_if=None)
```

- `when`: a condition built from a reference and a comparison (`>=`, `>`, `<=`, `<`) with a finite
  number:
  - `sf.agreement() >= 0.7`. `GA-1` only `>=` or `>`, and a threshold in [0, 1] (part 5).
  - `sf.signal("x").chosen() <= 3.0`: the declared signal of the member that the vote chose.
  - `sf.signal("x").mean() > 0.5`: the mean of the declared signal over the members.
  - `GA-2` `x` must be a declared name of the block (part 5: an E4a key such as `cost_usd` is not a
    gate input).
- The comparison is the condition that **keeps** the vote answer (part 5, P4).
- `then`: a `sf.Vote(...)`. `GA-3` any other value is refused: "sf.Gate then= takes sf.Vote until
  E4c" (D5).
- `otherwise`: `"abstain"` (reason `gate_not_met`), a `sf.JudgePick(...)`, or a
  `sf.Synthesize(model, prompt=...)` with a route or a `sf.Model`. `GA-4` a `Synthesize` of a
  nested recipe is refused (part 5: one model call).
- `abstain_if`: `ref.between(lo, hi)`, a closed band with `lo <= hi`, both finite. `GA-5` `ref`
  must be the same reference as in `when` (O5): "abstain_if must read the same number as when".
  Inside the band the step abstains with `in_band` (part 6).
- `GA-6` (O14) `then=sf.Vote(over=...)` with an extractor that has arguments (`"field:<path>"` or
  `sf.Extract(...)`) is refused: "a gated vote reads a rule name in over= until E4c".
- The docstring and the README say: in E4b the `otherwise` call runs on every Case, and E4c will
  skip it when the gate passes (D5).

## 8. Write: `sf.Synthesize`

```python
sf.Synthesize(model, *, prompt=None)
```

- `model`: a route string, a `sf.Model`, or a recipe (§1).
- `prompt`: the writer prompt. `SY-1` it is refused when `model` is a `sf.Model` that has a prompt,
  or a recipe that is not a `sf.Model`. With no prompt, the default synthesis prompt of today
  applies (`S/_evaluation/policy.py:11`).
- Input (D6): right after `Fanout`, the model gets today's Fusion context (`input` and `outputs`,
  or `panel` with a quorum). After `Rank` or `Filter`, it gets the `{"input", "selected"}` envelope
  (part 1). After `Concat`, it gets the joined text (`all@1` has no envelope,
  `E/combine/operators/selection.py:263`). The docstring says all three.

## 9. References

- `sf.signal(key)`: the keys of today (`S/_signals.py:24-80`): `cost_usd`, `latency_ms`,
  `tokens_in`, `tokens_out`, `score:judge`, `field:<path>`, or a declared name. Comparisons as
  today. New: `.chosen()` and `.mean()` return a gate reference (§7). `SI-1` on an E4a key they
  raise (part 5 hint).
- **Strings:** every `by=` and `weights=` takes a key string. The string goes through the same
  check as `sf.signal(key)`, with the same messages. `where=` takes only a condition value, not a
  string.
- `sf.agreement()`: the gate reference for the vote agreement.
- `sf.field(path, *, normalize=None)`: a JSON field reference for `sf.First`. It has only `==`.
  `SI-2` other operators raise: "sf.field compares with == only; use sf.signal('field:...') for
  numbers".
- `sf.matches(pattern, *, ignore_case=False)`: unchanged.
- **Extractors (`over=`):** a rule name string (`"last_line"`, `"last_number"`, `"boxed"`,
  `"whole"`, `"json"`, `"benchmark"`, `"inspect_number"`, `"inspect_aime"`), the same name with a
  pinned version (`"last_line@1"`, which the url4 rebuild writes today), `"field:<path>"` (the JSON
  field text), or a `sf.Extract(rule, normalize=None, **args)` value (for `regex` and the others
  with arguments). `EX-1` any other string is refused with the list of rule names.
  `"field:<path>"` in `over=` is an extractor, not a signal: it reads the field text as the answer.
- **Erratum E3:** `Median` and `Mean` have no `normalize=`; their normalizer is always numeric, and
  an `over=sf.Extract(...)` with a non-numeric normalizer is refused. EX-2 below applies to `Vote`
  only.
- `normalize=` on a step takes a name or a pinned name (`"text"`, `"text@1"`). `EX-2` a step whose
  caller **passes** `normalize=` (a sentinel default tells it apart, as `_DEFAULT_NORMALIZE` does
  today, `S/reducer.py:280-291`) together with `over=sf.Extract(..., normalize=...)` is refused: "set
  normalize on sf.Extract or on the step, not on both". With `over="field:<path>"` the step's
  normalizer applies: its default (`text` for `Vote`, `numeric` for `Median` and `Mean`) or the
  passed value.
- **Judge direction for weights (O12):** `Vote(weights="score:judge")` uses each score as it is. A
  rubric where a lower number is better gives the wrong members more weight; the `sf.Vote` docstring
  and the README say so.

## 10. Deleted public names

`sf.Pick`, `sf.Reduce`, `Recipe.then` (`sf.Fusion` stays as the shortcut of §3b, revised
2026-10-20). Deleted parameters: `Judge(returns=, order=)`,
`Rank(by=<Judge>, by_field=, by_signal=)`, `Filter(judge=, extract=)` (also the form
`Filter(where=<signal comparison>, extract=...)`, FI-1), `Vote(extract=, judge=, gate=)`,
`Median/Mean(extract=)`, and the `sf.Gate(observe, cmp, threshold, *, otherwise, abstain_band)`
signature. Each old class stays an internal compile node with a `Node` name (O7).

## 11. Acceptance

- Every name in §3–§9 is in `sf.__all__` and in the public surface snapshot. Every name in §10 is
  not.
- Every `CH-`, `FA-`, `JU-`, `RA-`, `FI-`, `RE-`, `GA-`, `SY-`, `SI-` and `EX-` rule has one test
  that checks its message.
- The refusals raise at construction or at the `>>` that closes the block, never after a model
  call.
- `MSG-1` (O13): a test scans (with `ast`) every string literal in a `raise` under `S/` and every
  public docstring of `sf.*`, and checks that none names `sf.Pick`, `sf.Reduce`,
  `returns=`, `by_field`, `by_signal`, `.then(` or `synthesizer`. **Erratum (7e review,
  2026-10-20):** `sf.Fusion` is the public shortcut of §3b, so `sf.Fusion` and `synthesizer=` are
  allowed ONLY in `S/_surface/fusion.py` (its messages and the `sf.Fusion` docstring), as a
  per-module exemption, not an allow-list entry; everywhere else `sf.Fusion`, the bare word
  `Fusion` and the word `synthesizer` stay forbidden. The allow list is explicit and
  short: internal-only messages that name `FusionNode` or its `synthesizer` field, and
  `CorrectiveLoop(judge=)`, which stays. Erratum U3c: no allow-list entry may hide a message that a
  new-surface value reaches at block close, for example "Rank keeps k=4 members but the Fusion has
  3" or "the synthesizer reads sf.signal('c'), which this Fusion does not declare"; bare "Pick ..."
  texts count too. Erratum U3d: `Judge` equality uses today's judge key, so the routes `"/p/j"` and
  `"p/j"` are unequal values with equal bytes (accepted).

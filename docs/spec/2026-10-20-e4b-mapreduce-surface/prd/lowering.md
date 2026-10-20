# PRD: the lowering (P0)

Spec: [00-overview.md](../00-overview.md). The lowering turns a chain of the new surface into the
internal nodes that the compile of today reads. The compile code (`S/_evaluation/candidate.py`,
`S/_evaluation/reducer_signals.py`, `S/_evaluation/combine_spec.py`, `S/_evaluation/topology.py`)
keeps its logic. So the url4 of a recipe is the url4 of today, except for the planned changes in §4
and the narrow steps in [narrow.md](narrow.md).

## 1. Principle

- **LO-1** The lowering is pure and deterministic. It runs at block close (§2.1) and at compile
  entry (§2.4). It never makes a call.
- **LO-2** The internal nodes are the classes of today, with their full parameters and their
  `_plan()` and `_from_spec()` code. At the swap (unit 7) each one gets its own name (O7):

| Today's class | Internal node |
|---|---|
| `Fusion` (`S/fusion.py`) | `FusionNode` |
| `Vote`, `Median`, `Mean` (`S/reducer.py`) | `VoteNode`, `MedianNode`, `MeanNode` |
| `Pick`, `Merge` (`S/fields.py`) | `PickNode`, `MergeNode` |
| `Rank`, `Filter`, `Concat` (`S/selection.py`) | `RankNode`, `FilterNode`, `ConcatNode` |
| `Judge` (`S/judge.py`, label and scores) | `JudgeNode` |
| `Gate` (`S/gate.py`) | `GateNode` |
| `Reduce` (`S/blocks.py`) | `ReduceNode` |

  `Model`, `Pipeline`, `CorrectiveLoop` and `SelfCorrective` keep their names and stay public. Until
  the swap, the lowering targets today's names; the rename is mechanical. This PRD uses the `Node`
  names.
- **LO-3** The compile sees only lowered values. No new-surface value reaches
  `S/_evaluation/candidate.py:_recipe` (`:308`) without the lowering.

- **LO-0** Until the swap, `lower()` is the identity on every value that is not a `_surface` value
  and holds no `_surface` value. So the unit 2 edit of the compile entry changes no existing
  behavior; a test compiles the existing golden set through the new entry and compares the bytes.

## 2. Mechanism

### 2.1 Block close

When a chain step closes a block (`CH-9`), `S/_surface/chain.py` builds a `_Block` record:

```python
@dataclass(frozen=True, slots=True)
class _Block:
    fanout: Fanout
    judge: Judge | None
    narrow: tuple[Rank | Filter | Concat, ...]   # 0..4
    terminal: Reducer | Gate | Synthesize        # the new-surface step values
    node: Recipe     # the lowered value: a FusionNode, or Pipeline([FusionNode, writer])
```

`node` is built in the `_Block` constructor, so every `FusionNode` rule raises at close (with the
O13 wording). The chain value stores its steps as given (for `repr` and equality) and a tuple of
lowered stages for the compile.

### 2.2 One block → internal nodes

| Block | Lowered `node` |
|---|---|
| `Fanout(m, ...) >> R` (R a reducer, not `Gate`) | `FusionNode(m', synthesizer=R', signals=..., quorum=..., name=...)` |
| `Fanout(m) >> Judge(J) >> R` (R reads `score:judge`) | as above; `R'` carries the judge (table below) |
| `Fanout(m) >> [Judge(J)] >> Gate(when, then=Vote(...), otherwise, abstain_if)` | `FusionNode(m', synthesizer=VoteNode(..., [judge=...,] gate=GateNode(observe, cmp, threshold, otherwise=o', abstain_band=band)))` |
| `Fanout(m) >> Synthesize(W)` | `FusionNode(m', synthesizer=W')`: `W'` = `Model(route, prompt=p)` or the lowered nested recipe |
| `Fanout(m) >> [Judge] >> N >> Synthesize(W)` (one narrow step) | `Pipeline([FusionNode(m', synthesizer=N'), W'])` |
| `Fanout(m) >> [Judge] >> N1 >> ... >> Nk >> R` (k ≥ 1, R a reducer) | `FusionNode(m', synthesizer=R' with narrow=(N1'...Nk'))` ([narrow.md](narrow.md)) |
| `Fanout(m) >> [Judge] >> N1 >> ... >> Nk >> Synthesize(W)` (k ≥ 2) | `Pipeline([FusionNode(m', synthesizer=Nk' with narrow=(N1'...Nk-1')), W'])` |

`m'`: the members, with `Fanout(prompt=)` applied (O6) and each closed block lowered.

**The narrow carrier.** "`R'` with `narrow=(...)`" means a private dataclass field `_narrow:
tuple[_NarrowPlan, ...] = ()` (`init=False`) on the internal reducer classes, set only by
`_surface/lowering.py` through `object.__setattr__`. It is not a constructor parameter and not a
public field, so the public surface snapshot does not move (the snapshot pins public names only).
`_ReducerPlan.narrow` (narrow §6) reads it.

The terminal and narrow mapping (`'` = the internal value; `s` = `sf.signal(key)` for a string key):

| Public step | Internal value (today's plan) |
|---|---|
| `Vote(over=e, normalize=n, weights=w)`, `e` a rule name (pinned or not) | `VoteNode(extract=op(e), normalize=n, weights=w')`; `op(e)` is the rule's operator name (`json` → `json_object`, erratum E2) |
| `Vote(over=e, ...)`, `e` = `"field:<path>"` or `sf.Extract(...)` | `ReduceNode("plurality" / "weighted", extract=Extract(...), ...)` (`S/blocks.py:643-665`) |
| `Vote(weights="score:judge")` + `Judge(J)` | `VoteNode(..., judge=JudgeNode(J, returns="scores"), weights=s)` |
| `Median`/`Mean(over=e, ...)`, `e` a rule name | `MedianNode`/`MeanNode(extract=e, ...)` |
| `Median`/`Mean(over=e, ...)`, `e` = `"field:<path>"` or `sf.Extract(...)` | `ReduceNode("median"/"mean", extract=Extract(...), ...)` |
| `ArgMax(k)` / `ArgMin(k)`, `k` not `score:judge` | `PickNode(by_signal=s, order="max"/"min", output=...)` |
| `ArgMax("score:judge")` + `Judge(J)` | `JudgeNode(J, returns="scores", order="max")` (select `max_score`) |
| `ArgMin("score:judge")` + `Judge(J)` | `JudgeNode(J, returns="scores", order="min")` (select `best_holder{order:min}`) |
| `First(where=sf.field(p, normalize=n) == v, output=o)` | `PickNode(p, equals=v, normalize=n, output=o)` |
| `JudgePick(J)` | `JudgeNode(J, returns="label")` |
| `Merge(fields)` | `MergeNode(fields)` |
| `Rank(k, by=key, order=o)` | `RankNode(k, by_signal=s, order=o)` |
| `Rank(k, by="score:judge", order=o)` + `Judge(J)` | `RankNode(k, by=JudgeNode(J, returns="scores"), order=o)` |
| `Filter(where=c, over=e)` | `FilterNode(where=c, extract=e)` (`e` only with `sf.matches`, FI-1) |
| `Filter(where=sf.signal("score:judge") <op> x)` + `Judge(J)` | `FilterNode(where=..., judge=JudgeNode(J, returns="scores"))` |
| `Concat(sep, label=l)` | `ConcatNode(sep, label=l)` |
| `Gate(otherwise=JudgePick(J))` | the part 5 fallback judge (`JudgeNode(J, returns="label")`) |
| `Gate(otherwise=Synthesize(W, prompt=p))` | the part 5 fallback writer `Model(W, prompt=p)` |

- **The judge direction.** With D2 the scores template has no direction (§4.1). `JudgeNode` keeps
  its `order` field only to choose the select step (`max_score` or `best_holder{order:min}`).
  - The min-order refusals in `RankNode`, `VoteNode` and `FilterNode` (`S/judge.py:275-300`) go
    away: a lowered judge is always `order="max"` for the template, and `Rank(order=)` sets the
    direction of `top_k`.
  - Today the `order="min"` judge writes the tail ` order=min` and the "A lower number" text. After
    the swap no judge writes them. The Engine never reads the template (`S/judge.py:37-39`).
    `ET/test_sdk_judge_order_contracts.py:84-86` pins those bytes and moves at the swap
    (migration §2).
- **The normalizer.** For `over=sf.Extract(rule, normalize=x)`, `x` is the normalizer. For a rule
  name, the step's `normalize=` is the normalizer. Both at once is refused (`EX-2`).

### 2.3 A chain → internal stages

- **LO-4** A chain lowers stage by stage: a `Model` lowers to itself, a nested `Pipeline` to its
  lowered stages, a closed block to its `node`, and a `Fanout` member to its lowered value. Unnamed
  nested Pipelines flatten (today).
- **LO-5** An unnamed chain whose only stage is a **closed block** lowers to that block's node,
  and its `optional` flag moves to the node. So `Fanout(m) >> Vote()` lowers to the same
  `FusionNode` as today's `sf.Fusion(m, synthesizer=sf.Vote())`, and its url4 bytes are the same.
  An unnamed chain with one `Model` stage stays a one-stage `Pipeline`, as today
  (`ST/test_pipeline_recipes.py:27`, `ST/test_fusion_quorum.py:154`).
- **LO-6** A named chain keeps its grouping (today: `_is_named`):
  `sf.Pipeline([sf.Fanout(m), sf.Vote()], name="x")` lowers to `Pipeline([FusionNode(...)],
  name="x")`.

### 2.4 Compile entry

- The recipe values enter the SDK at more than one place. `lower()` runs **once**, at the first of
  them, and every later place reads the lowered value:
  - `S/_evaluation/model.py:318-335` (`_candidate_values`: the `isinstance(Recipe)` check and the
    names) — the lowering runs here;
  - `S/_evaluation/compilation.py:38` (`rewrite_fusion_recipe`, `_check_rewritten_names`);
  - `S/_evaluation/runner.py:218`, `:228` (`recipes_need_operators`);
  - `S/_evaluation/candidate.py:110`, `:132` (`compile_candidate`, `rewrite_fusion_recipe`);
  - the url4 render entry (`S/url4.py`, the `Url4` build from a recipe).
  The unit spec lists every call site that it finds with `rg "rewrite_fusion_recipe|_candidate_values|recipes_need_operators"`.
- `S/_evaluation/fusion_recipe.py` and the `context` op are deleted with the public `sf.Reduce` at
  the swap (O1).
- `_warn_judge_writers` (`:131`) runs **before** the lowering today on purpose, so it reports the
  stage positions that the user wrote (`:129-131`). It keeps that rule and today's message text;
  the position it prints is the 1-based index of the stage in the user's chain, where a closed block
  counts as one stage. WJ-1 pins the full message for a chain with a judge block and a writer
  stage. Erratum U3b: a judge → writer pair **inside** one block (a block that lowers to
  `Pipeline([FusionNode, W])`) warns with today's message, which names the block's lowered Pipeline
  (`'a+b->b'`) and its stages 1 and 2.

## 3. Parity table (the notebook cases)

"Same" = the url4 bytes of the new form equal the bytes of today's form. "Changes" = a planned
change of §4, which happens at the swap. Before the swap, every row compares with today's bytes
through the old surface in the same process (units 2–6): a §4.1 row with today's `@1` judge
form, and a §4.2 row with today's `by_signal` form (S5 with S8, S7 with `Rank(by_signal=...)`).

| Case | New form | Today's form | Bytes after the swap |
|---|---|---|---|
| S1 | `Fanout(R) >> Median(over="last_number", select="value")` | `Fusion(R, synthesizer=Median(extract="last_number", select="value"))` | same |
| S2 | `Fanout(R) >> Median(over="last_number")` | `Fusion(R, synthesizer=Median(extract="last_number"))` | same |
| S3 | `Fanout(R) >> Mean(weights=(1, 1, 2))` | `Fusion(R, synthesizer=Mean(weights=(1, 1, 2)))` | same |
| S4 | `Fanout(J) >> Mean(over="field:answer", weights="field:confidence")` | `Fusion(J, synthesizer=Reduce("mean", extract=Extract("field", path="answer"), weights=signal("field:confidence")))` | same (through `ReduceNode`) |
| S4′ | `Fanout(J) >> Median(over="field:answer", weights="field:confidence", select="value")` | the `Reduce("median", ...)` form | same (through `ReduceNode`) |
| S5 | `Fanout(J) >> ArgMax("field:confidence", output="answer")` | `Fusion(J, synthesizer=Pick("confidence", order="max", output="answer"))` | **changes** (§4.2): now the S8 bytes |
| S7 | `Fanout(J) >> Rank(k=2, by="field:confidence") >> Synthesize(W, prompt=P)` | `Pipeline([Fusion(J, synthesizer=Rank(k=2, by_field="confidence")), Model(W, prompt=P)])` | **changes** (§4.2) |
| S8 | `Fanout(J) >> ArgMax("field:confidence", output="answer")` | `Fusion(J, synthesizer=Pick(by_signal=signal("field:confidence"), order="max", output="answer"))` | same |
| S9 | `Fanout(J) >> Filter(where=signal("field:confidence") > 0.7) >> Synthesize(W, prompt=P)` | `Pipeline([Fusion(J, synthesizer=Filter(where=...)), Model(W, prompt=P)])` | same |
| S10 | `Fanout(R) >> Judge(JR, rubric=RM) >> Rank(k=2, by="score:judge") >> Synthesize(W, prompt=P)` | `Pipeline([Fusion(R, synthesizer=Rank(k=2, by=Judge(JR, returns="scores", rubric=RM))), Model(W, prompt=P)])` | **changes** (§4.1) |
| S10′ | `... >> Judge(...) >> Filter(where=signal("score:judge") >= 7) >> Synthesize(...)` | `... Filter(where=..., judge=Judge(..., returns="scores"))` | **changes** (§4.1) |
| S11 | `Fanout(R) >> Judge(JR, rubric=RM) >> ArgMax("score:judge")` | `Fusion(R, synthesizer=Judge(JR, returns="scores", rubric=RM))` | **changes** (§4.1) |
| S11′ | `Fanout(R) >> Judge(JR, rubric=Rm) >> ArgMin("score:judge")` | `Fusion(R, synthesizer=Judge(JR, returns="scores", rubric=Rm, order="min"))` | **changes** (§4.1) |

Every README recipe and every url4 golden file is in the parity set too
([migration.md](migration.md) §3). Each one is "same" unless it has a scoring judge or a field pick.

## 4. Planned byte changes (at the swap)

### 4.1 Neutral judge scores template (D2)

- The scores template id becomes `judge-template@2`. The first line follows today's convention
  (`S/judge.py:45-47`, `:82-97`): `judge-template@2 returns=scores` for the outputs form, and
  `judge-template@2 returns=scores input=panel` for a quorum panel. No `order=` tail.
- The format text (`S/judge.py:67-71`) changes its last sentence from "A higher number means a
  better answer." to "Score each member as the rubric says." The rest of the text keeps its bytes.
  The unit pins the full template bytes in a test.
- The label template keeps `judge-template@1 returns=label` (and ` input=panel`) and its bytes.
- The url4 recovery (`S/judge.py:272`, `:287`) accepts `@2` scores and `@1` label. It refuses `@1`
  scores and any `@3` with "unsupported judge call" (A0: no old recipe is read).
- Effect: every recipe with a scoring judge gets new bytes, and the gateway request cache misses
  one time for those judge calls.

### 4.2 Field picks read a signal (D3)

- `ArgMax`/`ArgMin`/`Rank` with `by="field:<path>"` compile to `by_signal{key:"field:<path>"}`, as
  `Pick(by_signal=...)` and `Rank(by_signal=...)` do today. No public step makes the `json_field` +
  `values` + `by_field{order}` path or the `scores{source:values}` path any more.
- Effect: a missing or non-number field excludes the member (`no_signal`) for every pick and rank
  (part 2).
- `PickNode`'s field form stays for `sf.First` (`by_field{order:"equals", ...}`).

## 5. Acceptance

- The parity test compiles both forms of every row in §3, and of every README and golden recipe,
  and compares the bytes: equal for "same" (units 2–6 and after the swap), and equal to the new
  golden for "changes" (after the swap).
- `lower()` is idempotent on a lowered value, and it never calls the network (a test with no
  transport).
- No new-surface value reaches the compile without the lowering (a test passes a chain to
  `compile_candidate` and checks that `_recipe` sees only internal classes).

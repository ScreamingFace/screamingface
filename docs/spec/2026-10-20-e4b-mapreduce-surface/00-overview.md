# E4b surface: map → select → reduce — overview

**Status:** approved by the owner on 2026-10-20 (spec, plan, O1–O14; O14 = refuse). **Epic:** E4b (OME-1290). **Leaf:**
OME-1653 (PR #1461). The change lands as new commits on top of #1461, so the E4b stack merges with
the final surface.
**Base:** branch `OME-1653-e4b-display-gate-sums-consistency` at `e4d44281c` (parts 4–7, on #1460
parts 2–3, on #1409 part 1). Worktree `.claude/worktrees/e4b-consistency`.
**Source:** the Product Owner notebook `e4b-combine-mapreduce.ipynb` (2026-10-20) and the owner
answers of 2026-10-20 (§5).

## 1. Summary

Today one object, `sf.Fusion(members, synthesizer=...)`, does the fan-out **and** the reduce, and
its `synthesizer=` slot takes values with four different output types: a computed value
(`Median`, `Mean`), a copied member (`Pick`, `Judge`), a new answer (`Model`), and a selection
that is not an answer (`Rank`, `Filter`, `Concat`). A selection must then go to a writer through a
second object, `sf.Pipeline`.

This change replaces the public recipe surface with one grammar, composed left to right with `>>`:

```
Fanout(members, signals=...)  >>  [Judge]  >>  [Rank | Filter]*  >>  terminal
        map                       score        narrow              reduce / write
```

- **Map:** `sf.Fanout` sends the input to every member and declares the signals.
- **Score:** `sf.Judge` is its own step. It puts `score:judge` on each member. It does not pick.
- **Narrow:** `sf.Rank` and `sf.Filter` make the panel smaller. A narrow step never ends a recipe.
- **Terminal:** one reducer (`Vote`, `Median`, `Mean`, `ArgMax`, `ArgMin`, `First`, `Merge`,
  `JudgePick`, `Gate`) or one writer (`Synthesize`). `Concat` is a narrow step that a `Synthesize`
  must follow.
- After the terminal, the chain can go on with more stages (`>> sf.Model(...)`, another
  `sf.Fanout(...)` block, a nested `sf.Pipeline`). `sf.CorrectiveLoop` and `sf.SelfCorrective`
  stay root recipes, as today (`S/recipe.py:83-84`); their members can be chains.

There is **no backward compatibility** (owner, 2026-10-20: the SDK is experimental). `sf.Fusion`,
`sf.Pick`, `sf.Reduce`, `Recipe.then`, `Judge(returns=, order=)`, `Rank(by_field=, by_signal=)`,
`Filter(judge=, extract=)`, `Vote(extract=, judge=, gate=)` and the old `sf.Gate(observe, cmp,
threshold)` signature go away. The new surface compiles to the **same url4 and the same combine
spec** as today, except for the four planned byte changes in §4.

One new Engine capability comes with it (owner answer A2): **narrow steps before the reduce** in
one combine call, so `Fanout >> Filter(...) >> Mean()` and `Fanout >> Rank(k=3, ...) >> Vote()`
run. Today the Engine sends a selection only to a next stage.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `ET/` = `apps/screamingface-engine/tests/unit/`,
`ST/` = `packages/screamingface/tests/`. Line numbers are on base `e4d44281c`.

## 2. The surface at a glance

Full signatures, rules and refusals: [prd/surface.md](prd/surface.md).

| Category | Public names |
|---|---|
| Chain | `>>` on every step and recipe; `sf.Pipeline(steps, *, name=None, optional=False)` is the explicit form |
| Recipes (stand alone) | `sf.Model`, `sf.Pipeline`, `sf.CorrectiveLoop`, `sf.SelfCorrective`; `sf.samples(...)` builds Models |
| Map | `sf.Fanout(members, *, signals=None, quorum="all", name=None, prompt=None)` |
| Score | `sf.Judge(model, *, rubric, params=None)` → `score:judge` |
| Narrow | `sf.Rank(k, *, by, order="max")`, `sf.Filter(*, where, over=None)`, `sf.Concat(separator=..., *, label=True)` |
| Reduce | `sf.Vote(*, over="last_line", normalize="text", weights=None, verify=None)`, `sf.Median(*, over="last_number", select="nearest", weights=None)`, `sf.Mean(*, over="last_number", select="value", weights=None)`, `sf.ArgMax(by, *, output=None)`, `sf.ArgMin(by, *, output=None)`, `sf.First(*, where, output=None)`, `sf.Merge(fields)` + `sf.FieldRule`, `sf.JudgePick(model, *, rubric, params=None)`, `sf.Gate(*, when, then, otherwise="abstain", abstain_if=None)` |
| Write | `sf.Synthesize(model, *, prompt=None)` |
| Signal sources | `sf.Verbalized`, `sf.Logprob`, `sf.Entropy`, `sf.Sum`, `sf.Consistency` (unchanged) |
| References | `sf.signal(key)` (now also `.chosen()`, `.mean()`), `sf.agreement()`, `sf.field(path)` (text compare), `sf.matches(pattern)`, `sf.Extract(rule, ...)` |

The 13 notebook cases in the new form ([prd/lowering.md](prd/lowering.md) §3 lists the url4 each
one gives):

```python
s1  = sf.Fanout(ROUTES) >> sf.Median(over="last_number", select="value")
s2  = sf.Fanout(ROUTES) >> sf.Median(over="last_number")
s3  = sf.Fanout(ROUTES) >> sf.Mean(weights=(1, 1, 2))
s4  = sf.Fanout(json_members()) >> sf.Mean(over="field:answer", weights="field:confidence")
s4m = sf.Fanout(json_members()) >> sf.Median(over="field:answer", weights="field:confidence", select="value")
s5  = sf.Fanout(json_members()) >> sf.ArgMax("field:confidence", output="answer")
s7  = sf.Fanout(json_members()) >> sf.Rank(k=2, by="field:confidence") >> writer()
s8  = sf.Fanout(json_members()) >> sf.ArgMax("field:confidence", output="answer")
s9  = sf.Fanout(json_members()) >> sf.Filter(where=sf.signal("field:confidence") > 0.7) >> writer()
s10 = sf.Fanout(ROUTES) >> sf.Judge(JUDGE, rubric=R_MAX) >> sf.Rank(k=2, by="score:judge") >> writer()
s10t= sf.Fanout(ROUTES) >> sf.Judge(JUDGE, rubric=R_MAX) >> sf.Filter(where=sf.signal("score:judge") >= 7) >> writer()
s11 = sf.Fanout(ROUTES) >> sf.Judge(JUDGE, rubric=R_MAX) >> sf.ArgMax("score:judge")
s11m= sf.Fanout(ROUTES) >> sf.Judge(JUDGE, rubric=R_MIN) >> sf.ArgMin("score:judge")
```

`writer = lambda: sf.Synthesize(WRITER, prompt=WRITER_PROMPT)`. S5 and S8 are now the same recipe,
because every `by=` reads a signal (D3).

Parts 2–7 in the new form:

```python
# declared signals (part 3) and a weighted vote
sf.Fanout(members, signals={"p": sf.Logprob("prob")}) >> sf.Vote(weights="p")
# a judge-weighted vote
sf.Fanout(members) >> sf.Judge(J, rubric=R) >> sf.Vote(weights="score:judge")
# the gate (part 5) with a writer fallback and the abstain band (part 6)
sf.Fanout(members, signals={"risk": sf.Sum({"a": 0.5, "b": 0.3}), "a": ..., "b": ...}) >> sf.Gate(
    when=sf.signal("risk").mean() <= 3.0, then=sf.Vote(),
    otherwise=sf.Synthesize(BIG), abstain_if=sf.signal("risk").mean().between(2.5, 3.5))
# consistency (part 7)
sf.Fanout(models, signals={"cons": sf.Consistency(n=5)}) >> sf.ArgMax("cons")
# new: narrow before the reduce (A2)
sf.Fanout(json_members()) >> sf.Filter(where=sf.signal("field:confidence") > 0.7) >> sf.Mean(over="field:answer")
```

## 3. Subsystems and ownership

| Subsystem | Owns | PRD |
|---|---|---|
| SDK chain and steps (new package `S/_surface/`: `chain.py`, `fanout.py`, `steps.py`, `judge.py`, `gate.py`, `synthesize.py`, `refs.py`; at the swap `S/__init__.py`, `S/recipe.py`, `S/pipeline.py`) | the public names, `>>`, the chain rules, the refusals | [surface](prd/surface.md) |
| SDK lowering (new `S/_surface/lowering.py`; `S/_evaluation/candidate.py` entry; today's classes become the `Node` classes at the swap) | chain → internal nodes → the url4 of today | [lowering](prd/lowering.md) |
| Engine narrow step (`E/combine/spec.py`, `E/combine/endpoint.py`, `E/combine/evidence.py`, `E/combine/ports.py`) and its SDK side (`S/_evaluation/combine_spec.py`, `S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`) | `narrow` in the spec, the evidence `narrow` record, reason `not_selected` | [narrow](prd/narrow.md) |
| SDK rebuild and display (`S/url4.py`, `S/_evaluation/topology.py`, `S/_ui/cards.py`, `S/_ui/combine_view.py`, `S/_ui/report_view.py`, `S/report.py` messages) | url4 → chain, `repr`, `to_python()`, cards, labels | [rebuild-display](prd/rebuild-display.md) |
| Tests, goldens, docs, notebooks, public docs | the move to the new surface | [migration](prd/migration.md) |

## 4. Wire changes

1. **Combine spec v1, additive:** a new optional key `narrow` (a list of narrow steps), with no new
   schema id. A spec without the key keeps its bytes ([narrow](prd/narrow.md) §2).
2. **Combine evidence v1, additive:** a new optional key `narrow` (one record per narrow step) and
   a new exclude reason `not_selected` ([narrow](prd/narrow.md) §4).
3. **Judge scores template:** first line `judge-template@2 returns=scores` (and
   `judge-template@2 returns=scores input=panel` for a quorum panel), with neutral text: the rubric
   alone says what a high number means (D2, [lowering](prd/lowering.md) §4.1). The label template
   keeps `judge-template@1`. Every recipe that has a scoring judge gets new url4 bytes, one time.
4. **Field picks:** `ArgMax("field:x")` and `Rank(by="field:x")` compile to `by_signal@1`, not to
   `json_field` + `by_field@1` / `scores{source:values}` (D3). Those recipes get new url4 bytes, one
   time.

No other byte changes. The url4 grammar, the topology kinds (`fusion`, `pipeline`, ...), the report
v1 kind values and the Engine operator ids stay the same. No new failure code. Changes 3 and 4
come with unit 1. Change 3 happens at the swap (unit 7). For change 4, the new-surface steps
lower to `by_signal` from unit 3; the old field form goes away at the swap.

## 5. Decisions

### Owner answers, 2026-10-20

| # | Question | Answer |
|---|---|---|
| A0 | Backward compatibility | None. The SDK is experimental. |
| A1 | Where the change lands | New commits on top of #1461 (OME-1653). The stack merges with the final surface. |
| A2 | `Filter >> Mean`, `Rank >> Vote` | Add the Engine narrow step now. |
| A3 | Rename `cost_usd` to `cost` | No. Keep `cost_usd` (DB-2). |
| A4 | Keep `sf.Fusion` as a shortcut | No. Delete it. |
| A5 | The recommendations of the 2026-10-20 review | Take all of them (D1–D10). |

### Design decisions (from the review, accepted under A5)

| # | Decision |
|---|---|
| D1 | One grammar: `Fanout >> [Judge] >> [narrow]* >> terminal`, and more stages after the terminal. |
| D2 | Neutral judge scores template. The rubric gives the direction. `ArgMax`, `ArgMin` and `Rank(order=)` read the same scores. `Rank` gets `order=`. |
| D3 | Every `by=` and `weights=` reads a signal. A missing value always excludes the member (part 2). The text compare moves to `sf.First(where=sf.field(path) == value)`. |
| D4 | Signals are declared on `sf.Fanout(signals=...)`, because Logprob, Entropy and Consistency change the fan-out calls. `sf.Judge` stays a separate step, because it is a later call. Strings work for the built-in keys. |
| D5 | One `sf.Gate(when=..., then=sf.Vote(...), otherwise=..., abstain_if=...)` with aggregate references. `then=` takes only a `Vote` until E4c. The docs and the report say that the `otherwise` call runs on every Case in E4b. |
| D6 | `sf.Synthesize` keeps the two input forms: the Fusion context after `Fanout`, the `{"input","selected"}` envelope after a narrow step. |
| D7 | A recipe is a chain of blocks. A stage can follow a terminal. |
| D8 | No `embedding:<model>` signal. |
| D9 | The label judge becomes `sf.JudgePick`. `Concat` is a narrow step; `Merge` is a reducer. |
| D10 | `quorum=` and `name=` are on `Fanout`; `optional=` stays on `Model` and `Pipeline`. |

### Orchestrator decisions (proposed; the owner confirms at spec review)

| # | Decision | Why |
|---|---|---|
| O1 | Delete `sf.Reduce` (the block form) from the public surface, and delete the `context` rewrite (`S/_evaluation/fusion_recipe.py`). The block form stays as the **internal** node `ReduceNode`: it is the lowering target when `over=` is an extractor with arguments (`"field:<path>"`, `sf.Extract(...)`), and the url4 rebuild of those specs (`S/blocks.py:643-665`, `:722-794`). Keep `sf.Extract`. | One spelling per recipe (A4). The internal answer reducers store `extract` as an op name only (`S/reducer.py:616`, `:736`), so the block form is the one path that compiles a field or regex extract today. |
| O2 | Delete `Recipe.then`. `>>` is the only chain operator. | One spelling. |
| O3 | The notebook's `Gate(when=..., else=...)` is not valid Python (`else` is a keyword). The keyword is `otherwise=`. | Syntax. |
| O4 | The aggregate references are methods: `sf.signal("x").chosen()`, `sf.signal("x").mean()`, and `sf.agreement()`. No top-level `sf.mean` or `sf.chosen`. | `sf.mean` next to `sf.Mean` is a trap. |
| O5 | `abstain_if=` must read the same reference as `when=` (the Engine band is on the gated number). | The part 6 band is one closed interval on the observed number. |
| O6 | `Fanout(prompt=...)` sets the prompt of each member that is a route string or a `Model` with no prompt. A member `Model` with its own prompt, or a member that is not a Model, is refused when `prompt=` is set. | One prompt rule, no silent override. |
| O7 | Every class of today's surface stays as an **internal** compile node with its own name, given at the swap (unit 7): `FusionNode`, `VoteNode`, `MedianNode`, `MeanNode`, `PickNode`, `RankNode`, `FilterNode`, `ConcatNode`, `MergeNode`, `JudgeNode` (label and scores), `GateNode`, `ReduceNode`. None is exported. The topology kind `fusion` and the report kind `fusion` stay on the wire. The cards show "fanout". | The compile has more than 40 `isinstance` sites on these classes (lowering §2). One name per class avoids two classes called `Rank`. The wire stays the same. |
| O8 | After a narrow step, only another narrow step, a reducer or `Synthesize` can come. `Fanout` or a `Model` after a narrow step is refused ("use sf.Synthesize"). | One clear way for a selection to reach a writer. Today a selection can go to any stage. |
| O9 | `sf.Judge` with no step that reads `score:judge` after it is refused. A second `sf.Judge` in one block is refused. | A judge call costs money. The Engine has one judge column per step. |
| O10 | A block holds at most 4 narrow steps. | A bound for the spec and the evidence. |
| O11 | A narrow step before `Merge`, `JudgePick`, or a `Gate` whose `otherwise` is not `"abstain"` is refused (rule `NR-C1`). | These steps make their own model call over the whole Fusion context (`S/fields.py:387`, `E/combine/endpoint.py:740-772`), so they would see the members that the narrow step left out. Giving them only the live set is a wire change. |
| O12 | The README and the `sf.Vote` docstring say: `weights="score:judge"` uses the score as it is, so a rubric where a lower number is better gives the wrong members more weight. | With D2 the template no longer says which direction is better, and the SDK cannot read the rubric. |
| O13 | Every user-facing message and public docstring names the new surface only. The messages that reach the user get new text at the swap: among others `S/fusion.py:126-127`, `:284`, `:296`, `S/reducer.py:382`, `S/recipe.py:81`, `:124`, `S/_evaluation/model.py:315`, `:326`, and the messages in `S/_evaluation/topology.py`, `linking.py` and `compilation.py`. `MSG-1` finds them by a scan, not by a list (surface §11). | A message that says "use sf.Pick" after `sf.Pick` is gone is a bug. |
| O14 | `sf.Gate(then=sf.Vote(over=...))` with `over=` an extractor with arguments (`"field:<path>"`, `sf.Extract(...)`) is refused (`GA-6`): "a gated vote reads a rule name in over= until E4c". Owner 2026-10-20: refuse (the other option was a gate on `ReduceNode`). | `VoteNode` holds an op name only and `ReduceNode` has no gate (`S/url4.py:564-566`). E4c reworks the gate. |

## 6. Units

The plan ([docs/plan/2026-10-20-e4b-mapreduce-surface.md](../../plan/2026-10-20-e4b-mapreduce-surface.md))
has the full table. In short:

1. Engine narrow step + SDK evidence decoder (`narrow`, `not_selected`, the judged set).
2. SDK chain core in the private package `S/_surface/`: `>>`, chains, `Fanout`, `Synthesize`,
   `Vote`/`Median`/`Mean`, the block rules, the lowering.
3. SDK steps in `S/_surface/`: `Judge`, `JudgePick`, `Rank`, `Filter`, `Concat`, `ArgMax`, `ArgMin`,
   `First`, `Merge`, signal strings, `sf.field`.
4. SDK gate in `S/_surface/`: `Gate(when, then, otherwise, abstain_if)`, `.chosen()`, `.mean()`,
   `agreement()`.
5. SDK narrow compile: chains with narrow steps → spec `narrow`.
6. SDK rebuild and display: url4 → chain (`_surface.rebuild`), `repr`, new card builders and the
   narrow chips. The new code is used by `_surface` values only; the old cards stay until the swap.
7. The swap: export `S/_surface/` as `sf.*`, rename the old classes to their `Node` names (O7), the
   `@2` template and the field-pick bytes (§4), the message rewording (O13), the move of the tests and
   goldens, the removal of the old names. One owner approval for all pinned edits.
8. Docs: README, CHANGELOG, notebooks, public docs, the PO notebook as an example.

Units 2–6 build the new surface in a **private package** that only new tests import, and compare
it with today's bytes. Snapshots: unit 1 changes the two v1 schema snapshots and the public surface
snapshot (`CombineEvidence.__init__` gets `narrow`, and `CombineNarrow` is new and public); units
2–6 change no snapshot; unit 7 regenerates the public surface snapshot. No existing test changes
before unit 7. Unit 1 runs in parallel with units 2–4.

## 7. Out of scope

- Skipping the `otherwise` call when the gate passes, `Route`, and cascades: E4c (OME-1291).
- `embedding:<model>` signals (D8).
- A gate on a reducer other than `Vote` (D5).
- A judge in a narrow step of a block that has a second judge (O9).
- Any change to the url4 grammar, the topology kinds or the report v1 kind values (O7).

## 8. Reading order

1. [prd/surface.md](prd/surface.md) (P0)
2. [prd/lowering.md](prd/lowering.md) (P0)
3. [prd/narrow.md](prd/narrow.md) (P0)
4. [prd/rebuild-display.md](prd/rebuild-display.md) (P1)
5. [prd/migration.md](prd/migration.md) (P1)
6. [test-plan.md](test-plan.md)

# PRD: narrow steps before the reduce (P0)

Spec: [00-overview.md](../00-overview.md). Owner answer A2. Today one combine call has one reduce
step and one select step (`E/combine/spec.py:284`). A selection (`top_k@1`, `kept@1`) is the select
step, and its output (the `selected` envelope) goes to the next Pipeline stage. This PRD adds an
ordered list of **narrow steps** that run before the main reduce, in the same combine call.

```python
sf.Fanout(J) >> sf.Filter(where=sf.signal("field:confidence") > 0.7) >> sf.Mean(over="field:answer")
sf.Fanout(R) >> sf.Judge(JR, rubric=RM) >> sf.Rank(k=3, by="score:judge") >> sf.Vote()
sf.Fanout(J, signals={"p": sf.Logprob("prob")}) >> sf.Filter(where=sf.signal("p") >= 0.5) >> sf.Rank(k=2, by="field:confidence") >> writer()
```

## 1. Terms

- **Narrow step:** one `(extract?, normalize?, reduce, select)` group whose select gives a member
  subset. **Main step:** the `extract, normalize, reduce, select` of today.
- **Live set:** the members that the next step reads. It starts as the answered members (a failed
  member is never live, as today). Each narrow step makes it smaller.

## 2. Spec wire (combine spec v1, additive)

A new optional key `narrow`. The SDK writes it only when the block has a narrow step before its
main step. The spec text is canonical JSON with sorted keys (`S/_evaluation/combine_spec.py:38-39`),
so the key has no free position. A spec without the key keeps its bytes.

```json
"narrow": [
  {"extract": null, "normalize": null,
   "reduce": {"op": "filter@1", "args": {"key": "field:confidence", "cmp": ">", "value": 0.7}},
   "select": {"op": "kept@1", "args": {}}}
]
```

- Each item has exactly the keys `extract`, `normalize` (both a step or `null`), `reduce` and
  `select` (both a step). `extra="forbid"`, as `_SpecModel` (`E/combine/spec.py:167-170`).
- `NR-S1` 1 to 4 items (O10). An empty list is invalid; the SDK leaves the key out instead.
- `NR-S2` Each item's `(reduce, select)` pair must be in the new table `NARROW_RULES`:

| Narrow reduce | Narrow select | From |
|---|---|---|
| `filter@1` (signal or pattern args) | `kept@1` | `sf.Filter` |
| `by_signal@1` | `top_k@1` | `sf.Rank(by=<signal>)` |
| `scores@1` (`source: judge`) | `top_k@1` | `sf.Rank(by="score:judge")` |

- `NR-S2b` Stage rules per item: `by_signal@1` and `scores@1` items have `extract: null` and
  `normalize: null`. A `filter@1` item with a signal comparison has both `null`. A `filter@1` item
  with a pattern may have an `extract`. `normalize` is set only with an `extract`.
- `NR-S3` Each item reads at most one signal (the rule of `E/combine/endpoint.py:991`, now per step:
  each narrow step and the main step count apart).
- `NR-S4` A narrow item that reads `score:judge` needs the judge reply in the combine context
  signals, as the main step does today (`E/combine/ports.py:632`).
- The JSON schema snapshot `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`
  gets the optional `narrow` property (a pinned file, owner approval).

## 3. Engine flow (`E/combine/endpoint.py`)

1. `_plan` (`:881`) resolves each narrow item into a `_NarrowPlan` (extract, normalize, reduce,
   select, signal read, exclusion rule, rank and cut hooks), with the same `_resolve`, `_bind` and
   `_exclusion` code as the main step, and checks `NARROW_RULES`.
2. After `_read_members` (`:1020`) and the signal columns (`:368`), a new function `_narrowed` runs
   the narrow plans in order. For each one:
   - It builds a `CombineInput` whose answers are the live members, and runs extract → normalize →
     reduce → select on it (the code of `_decide`, `:588`).
   - **The judged set.** The judge saw every answered member, and `parse_scores` needs the reply
     keys to equal its member set exactly (`E/combine/ports.py:688-693`). So `CombineInput` gets a
     new field `judged: tuple[str, ...]`: the `present` set of the input **before any narrow
     step** (it also holds members that failed after they sent an output, as `present` does
     today), the same for every step. The `scores@1` op (`E/combine/operators/judge.py:61-66`)
     parses the reply over `judged`, then keeps the scores of the live members only. With no narrow
     step, `judged == present` by this definition, so the main step of today does not change.
   - A live member that the step's exclusion rule leaves out (X2: no value for the signal) is
     excluded with reason `no_signal`.
   - A live member that the select does not choose is excluded with the new reason `not_selected`.
   - The chosen members are the new live set.
   - A select that raises `NoVotes` (no member kept: `no_votes`; fewer than `k` scored:
     `cut_not_met`) makes the call abstain with that reason. The gate does not run
     (`gate=_not_run(spec)`, as a main-step abstain, GR-I1).
3. The main step runs on the live set, as today. Its exclusion, rank and cut rules apply to the
   live members only. Its `agreement` is over its own participants (today's definition). The main
   step `scores@1` (`ArgMax`/`ArgMin("score:judge")` after a narrow step) parses over `judged` too.
4. Consistency (part 7) counts the samples of every member before the narrow steps, with the main
   step's extract and normalize (part 7 rule).
5. A gate (`sf.Gate(then=Vote(), otherwise="abstain")`) in a block with narrow steps gates the main
   vote on the live set. `mean:<name>` is the mean over the live members (`observed_number` reads
   `combine_input.members`, which is the live set), and `chosen:<name>` reads the chosen member.
   A gate with a model fallback cannot follow a narrow step (`NR-C1`, O11).
6. `label@1` (`JudgePick`), `field_rules@1` (`Merge`) and a gate fallback call never run after a
   narrow step (`NR-C1`), so their whole-context parse (`E/combine/endpoint.py:740-772`) does not
   change.

## 4. Evidence (combine evidence v1, additive)

### 4.1 Member rows

- `ExcludeReason` (`E/combine/ports.py:90`) gets `"not_selected"`.
- A member that a narrow step leaves out has `status: "excluded"` and `reason: "not_selected"` or
  `"no_signal"`.
- **Row fields.** `value` is the main step's extracted value when the main step has an extract,
  else `null`. `score` and `rank` come from the main step only, so a left-out member has
  `score: null` and no `rank`; AR-I4 (ranks are 1..n over the scored rows,
  `E/combine/evidence.py:308-313`) keeps holding. `signals` hold every key that **any** step of
  the call reads (the narrow keys and the main key) plus the declared names, so a reader can check
  each narrow decision from the evidence.
- A narrow step's scores and ranks go in its narrow record (§4.2).

### 4.2 The `narrow` record

A new optional evidence key `narrow`, written after `cut` and before `consistency`, only when the
spec has `narrow`:

```json
"narrow": [
  {"select": "kept@1", "signal": "field:confidence", "kept": ["member_1", "member_3"]},
  {"select": "top_k@1", "signal": "score:judge", "kept": ["member_3"], "cut": {"k": 1, "order": "max"},
   "scores": {"member_1": 0.4, "member_3": 0.9}, "ranks": {"member_1": 2, "member_3": 1}}
]
```

- One record per narrow item, in spec order, up to the step that abstained (that step is recorded
  with `kept: []`).
- `select`: the pinned select op id. `signal`: the key that the step read (`field:confidence`,
  `score:judge`, a declared name), absent for a pattern filter. The evidence `signal` key of today
  stays the main step's key (`E/combine/endpoint.py:1210`). `kept`: member ids in author order.
  `scores`: the step's score for each live member that had one. `cut` and `ranks`: only for `top_k@1` (the part 2 rules of
  `top_k_ranks` and `CutRecord`, `E/combine/evidence.py:106-111`). Keys that are not set are absent.

### 4.3 Invariants

| Id | Rule |
|---|---|
| NR-I1 | `kept` of item i is a subset of `kept` of item i−1. `kept` of item 0 is a subset of the answered members. |
| NR-I2 | A member with reason `not_selected` or a narrow `no_signal` is in no later `kept`, and is not in `chosen` (CE-I3 holds, `E/combine/evidence.py:312`). |
| NR-I3 | Each excluded member is excluded by exactly one step: the first step that left it out. |
| NR-I4 | `reason == "not_selected"` only when the evidence has `narrow`. |
| AR-I3′ | `reason` is in `{no_signal, no_weight, not_selected}` exactly when `status == "excluded"` (`E/combine/evidence.py:73-74`, extended). |
| NR-I5 | A narrow abstain writes the records up to the abstaining item, `result.reason` in `{no_votes, cut_not_met}`, and `gate` not run. |
| NR-I6 | `dropped` still counts failed members only. |

- The evidence schema snapshot `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`
  gets `narrow` and the enum value (a pinned file, owner approval).

## 5. Places that assume one step today

Each place below reads only the main step today. With `narrow`, each one follows the rule given.

| Place | Rule with `narrow` |
|---|---|
| `E/combine/endpoint.py:482` `_recorded_keys` | the union of the keys that every step reads |
| `E/combine/endpoint.py:352-356` `parse_context(sources_expected=...)` | expected when any step reads an accounting key |
| `E/combine/endpoint.py:1027-1037` `_read_members` (Answer signals) | every key that any step reads |
| `E/combine/endpoint.py:1182-1218` `_evidence` (rows, `dropped`) | rows for every member; `dropped` counts failed members only (NR-I6) |
| `E/combine/endpoint.py:991` one-signal rule | per step (NR-S3) |
| `S/_evaluation/combine_spec.py:133` `accounting_signal` (used at `S/_evaluation/candidate.py:739`) | true when any step reads an accounting key, so the member sources go in the context |
| `S/fusion.py:213-286` `_check_reads`, `_check_weight_source` | run on every step |
| `S/_evaluation/combine_spec.py:24`, `:180` `_is_spec` | accepts the `narrow` key |
| `S/_evaluation/combine_spec.py:220-242` `spec_operator_pairs` | yields the ops of the narrow items too, so the url4 recompile pins them (RB-1) |

## 6. SDK side

- **Compile** (`S/_evaluation/combine_spec.py`): the internal reducer plan (`S/reducer.py:84`,
  `_ReducerPlan`) gets a `narrow` tuple of step groups, made from each narrow step's own plan. The
  judge signal call is planned once when the judge has more than one reader.
  `combine_spec_text` writes `narrow` (§2).
- **Evidence** (`S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`): a new frozen record
  `CombineNarrow(select, signal, kept, cut, scores, ranks)` and `CombineEvidence.narrow`, decoded as an optional
  key. `sf.Answer.reason` gets `"not_selected"` (`S/answer.py:27-30`). `case.answers()` gives the
  excluded member with its reason (part 2 rule).
- **Display** ([rebuild-display.md](rebuild-display.md) §4): one chip per narrow step, and the member
  cell says which step left the member out.
- **Rebuild** ([rebuild-display.md](rebuild-display.md) §1): a spec with `narrow` rebuilds as the
  narrow steps in the chain, in order.

## 7. Contract data

- New `ET/data/combine_contract/narrow_evidence_cases.json`: filter then mean, rank then vote,
  filter then rank then the selection envelope, a narrow abstain (`no_votes`, `cut_not_met`), a
  narrow `no_signal`, a judge read by a narrow step and by the main vote, a judge rank **after** a
  filter (the judged set), a judge `ArgMax` after a filter, and an abstain-fallback gate after
  narrow with `mean:` over the live set.
- New url4 fixtures `ET/data/combine_contract/narrow_filter_mean_candidate.url4` and
  `narrow_rank_vote_candidate.url4`, compiled by the SDK and read by the Engine test.

## 8. Acceptance

- Each NR-S and NR-I rule has one Engine test.
- The SDK decodes every case in `narrow_evidence_cases.json`, and an evidence with no `narrow` key
  decodes with `narrow is None` (old bytes).
- A spec without `narrow` gives byte-identical evidence to today (the existing contract cases pass
  with no edit).

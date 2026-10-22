# PRD: Skip members — set-valued selection inside a Fanout

**Source:** epic OME-1291 behavior 1 ("Papers that choose a subset or a topology … unselected agents
make no calls"), ans:Q8, ans:Q10, ans:Q16 · **Priority:** P1 (PR-2, selection)
**Lifecycle:** planned (new member form) on top of existing Fanout / quorum / combine code
**Owner:** unassigned
Paths: [erd §1, §2, §3, §4](../erd.md) · contracts: C1, C4, C11 · components:
[branch-core](branch-core.md), [selectors](selectors.md) · display: [report](report.md)

## 1. Summary and user story

As a researcher who reproduces a manager-style method (a manager picks 2 of 10 agents, an
orchestrator calls only the tool-agents that claim the skill, a router that picks a subset of a
panel), I want each Fanout member to run only when a selector picked its label, so that the
members that were not picked make zero model calls, the block's reducer or writer joins
only the picked members, and the report shows which members were not selected and why.

```python
sel = sf.LabelModel("openrouter/openai/gpt-4o-mini", labels=["math", "code", "web"], multi=True)
sf.Fanout([
    sf.Gate(when=sf.labels(sel).has("math"), then="openrouter/deepseek/deepseek-r1"),
    sf.Gate(when=sf.labels(sel).has("code"), then="openrouter/qwen/qwen3-coder"),
    sf.Gate(when=sf.labels(sel).has("web"),  then=web_agent_pipeline),
]) >> sf.Synthesize("openrouter/openai/gpt-5")
```

## 2. Background and constraints

- "Papers that choose a subset or a topology, not a single named model. Same contract: unselected
  agents make no calls. The selector's output is a set of labels, or a small graph, rather than one
  label." [stated epic]
- "Whether a set-valued selector … is a Router that returns several labels, or a Cascade of
  optional branches. One implementation should cover both, or the manager papers will not fit the
  one-label API." [stated epic, open question]
- Set-valued selection is in v1. [stated ans:Q8]
- Only `sf.Gate`; no `sf.Route` class. [stated ans:Q9]
- A Gate is not a Fanout member. [stated ans:Q10]
- The one exception: a skip-Gate (a Gate with no `otherwise`) may be a Fanout member. An
  unselected member makes zero calls and shows as `not_selected`; the Fanout's reducer joins the
  selected ones. [stated ans:Q16]
- One selector instance is evaluated once per Case and shared by every Gate that reads it.
  [stated ans:Q12; component [selectors](selectors.md)]
- `sf.labels(sel).has("x")` is the set-valued condition form; Keywords and LabelModel both take
  `multi=True`. [implied — ans:Q8; erd §1, §2]

### 2.1 Current behavior

- `Fanout(members, *, signals, quorum="all", name, prompt)` checks its members with the FusionNode
  rules (`S/_surface/fanout.py:46-62`, `S/fusion.py:423-430`); a member is a route string or a
  Recipe (`Model | FusionNode | Pipeline`, `S/recipe.py:138-145`) and may be `optional=True`
  [existing]. A Gate is a Step, not a Recipe (`S/_surface/gate.py:28-29`), so today a Gate member is
  refused [existing].
- `quorum` is `"all"` or an integer from 0 to the member count (`S/fusion.py:399-406`) [existing].
- With a quorum or an optional member, the compiler builds one url4 panel: each member is one
  slot `src(expr(...), name="member_i", weight=1.0, required=not optional)` and the panel is
  `expr(*slots, broadcast=<reads rows>, params={"quorum": N})`, `N = len(members)` for `"all"`
  (`S/_evaluation/candidate.py:378-429`) [existing]. A reducer reads the broadcast rows (one JSON
  row per member that answered); a model writer reads the text panel [existing].
- url4 counts every resolved slot toward the quorum and raises `QUORUM_NOT_MET` below it
  (`U/dag/_wiring.py:213-225`, `U/dag/nodes/_shared.py:249-261`) [existing]. An optional slot that
  fails returns a `SourceFailure` value and leaves no row; a required slot that fails fails the
  expression even when the quorum is met (`U/dag/nodes/guard.py:96-140`, Spec C §10) [existing].
  The guarded subtree runs on an isolated sub-executor; shared bindings flow in as reference edges
  and resolve once (`U/dag/nodes/guard.py` docstring) [existing].
- The combine call reads a member that a quorum panel left out as `fail` with reason `missing`
  (`E/combine/endpoint.py:1339-1343`); the judged set is the members that sent an output
  (`E/combine/endpoint.py:1316-1323`); an empty panel abstains with `no_votes`
  (`E/combine/endpoint.py:454-457`) [existing].
- `ExcludeReason = no_signal | no_weight | not_selected`; `not_selected` belongs to a narrow step
  (`E/combine/ports.py:89-91`). Invariant NR-I4: "not_selected goes with a narrow record, and only
  with it" (`E/combine/evidence.py:378-386`). An `excluded` record means "the member answered and a
  rule of the step left it out" (`E/combine/evidence.py:58-61`). `dropped` counts only failed
  members (`E/combine/evidence.py:357-358`) [existing].
- The combine context keys are `input, outputs | panel, samples, signals, sources`
  (`E/combine/spec.py:65`; writer order `S/_evaluation/candidate.py:980-1008`) [existing].
- A consistency source compiles one sample panel per member with `quorum=0` and optional slots
  (`S/_evaluation/candidate.py:761-800`) [existing].

**Delta.** A new member form (the skip-Gate), its compiled slot shape, one new optional combine
context key `selection`, one new optional combine-evidence key `skipped`, an Engine-side quorum
check over the selected members, and an extended NR-I4.

Compiled shape [proposed — [branch-core](branch-core.md) D8]:
- The selector source and every member's DECIDE (`gate_N_decide`) sit before the panel, outside
  the member slots. The combine context `selection` maps each skip-Gate member to
  `$gate_N_decide`, so the combine call reads the decisions without reading a failed slot.
- A Fanout with a skip-Gate member always takes the panel compile path, also under
  `quorum="all"`, where a Fanout with no optional member compiles flat today [existing
  `S/_evaluation/candidate.py:361-376`]. [proposed — review 3 F8]
- Each member slot holds OPEN, the gated iterate with the member recipe and JOIN. Under
  `quorum="all"` (the default) the slot is required, as a plain member is today; the url4 panel
  keeps `quorum = len(members)`. Under a numeric quorum the slot is `;optional` and the panel
  carries url4 `quorum=0` (the consistency precedent [existing
  `S/_evaluation/candidate.py:761-800`]).
- An unselected member's JOIN returns `""` and raises nothing. The slot resolves, so the broadcast
  panel holds an empty row for it; the combine call excludes that row through `selection` (the
  member's DECIDE record says not selected). Its record is JOIN's record on `op_gate_N` with
  `result` null ([branch-core](branch-core.md) D3, D8); the block's combine evidence lists the
  member in `skipped`.
- A selected member that fails under `quorum="all"` fails its required slot, and url4 fails the
  panel with that member's own code [existing `U/dag/nodes/guard.py:96-140`], as for a required
  member today (ans:Q23). No failure code is published on a call and no internal code exists.
  [proposed — review 2 F5]
- A member Gate omits `otherwise=`: the sentinel default `None` means "skip" for a member and
  `"abstain"` elsewhere ([gate](gate.md) delta 2); "skip" is never a public value.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **SM-1 Unselected members make zero calls.** Given a Fanout of three skip-Gate members over one
  multi selector, When the selector returns `{"math", "web"}`, Then the `code` member makes zero
  model calls (also no logprob-carrying call), and the two selected members run in
  parallel. [stated epic; stated ans:Q16]
- **SM-2 The block joins only the selected members.** Given SM-1 with a reducer step (`sf.Vote()`),
  When the combine call runs, Then only the two selected members are voters; the `code` member's
  evidence record is `status: "excluded"`, `reason: "not_selected"`, with `raw`, `value`, `score`,
  `weight` null and every signal null; the evidence key `skipped` is `["member_2"]`; `dropped`
  does not count it. [stated ans:Q16; proposed key]
- **SM-3 One selector evaluation per Case.** Given three skip-Gate members that read the same
  LabelModel, When the Case runs, Then the selector makes exactly one model call, placed before the
  panel and outside the member slots, and every member's decision record holds the same selector
  record. [stated ans:Q12]
- **SM-4 Writer joins the selected members.** Given SM-1 with `>> sf.Synthesize(m)`, When the block
  runs, Then the writer receives the E4b selection envelope `{"input": …, "selected": [...]}` with
  the selected members that answered, in author order, and never an empty slot for a skipped
  member. [proposed — reuse of the E4b narrow → writer envelope]
- **SM-5 Keywords as a set selector.** Given `sf.Keywords([...], multi=True)`, When two rules match,
  Then both labels are selected (declared order), with no model call for the selector.
  [stated epic: "Keywords … No model"; stated ans:Q8]

### 3.2 Error paths

- **SM-6 Nothing selected.** Given a multi selector that returns `[]` (no rule matched, or the reply
  had no known label), When the block runs, Then no member runs, the combine call abstains with
  `no_votes` (the existing empty-panel rule) and the Case scores 0 with `abstained: true`; the
  selector record shows `parse: "no_match"` (or `unrecognized` / `unparsed`). [implied — existing
  `E/combine/endpoint.py:454-457`; proposed]
- **SM-7 A selected member fails.** Given `quorum="all"` (the default) and two selected members of
  which one fails permanently, When the panel resolves, Then the member's required slot fails the
  panel and the Case fails with that member's own failure code (for example `provider_refusal`),
  the same as a required member today; the combine call does not run. With a numeric quorum (an
  `;optional` slot) the failed member's record is `fail` / `missing`, and the Case goes on while
  the remaining selected members meet the floor. [stated ans:Q23]
- **SM-8 Refused member forms.** Given a Fanout member `sf.Gate(..., otherwise=X)` (any otherwise,
  also `"abstain"`), or a skip-Gate whose `then` is a step or a word, or a skip-Gate whose `when`
  reads a panel ref (`sf.agreement()`, `sf.signal(...)`), When the Fanout is built, Then it raises
  with a message that names the member position: "a sf.Fanout member may be a sf.Gate only without
  otherwise= and with a recipe in then=". [stated ans:Q10, ans:Q16]
- **SM-9 Selector placement error.** Given a skip-Gate member whose selector is used by no other
  member and whose model call would sit inside the member slot, When the block compiles, Then the
  compiler still hoists the selector call before the panel (never inside a slot), so a member slot
  never holds a model selector call. [stated ans:Q12; proposed]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| SM-10 | Skipped slot gives an empty row that the combine excludes | [proposed — review 2 F5] | H×H | Given a skipped member, Then its JOIN returns `""` and raises nothing, the broadcast panel holds an empty row for it, the combine call excludes it through `selection` (never an answer, never counted toward a quorum floor), and no failure reaches the Case. |
| SM-11 | Quorum counts selected members | [proposed — review 3 F4] | H×H | Given `quorum=2` and three selected members, Then the block needs 2 answers; given `quorum=2` and one selected member, Then the effective floor is `min(2, 1) = 1`; below the floor the combine call raises `quorum_not_met`, a new declared, permanent failure code (Engine `DECLARED_FAILURE_CODES` + `ENGINE_ERROR_CODES` + SDK mirror, built in this PR, PR-2; erd §6, contracts C10). The numeric floor is checked by the combine call over the selected members, and the url4 panel carries `quorum=0` with `;optional` slots. Given `quorum="all"`, Then every selected member must answer: its slot is required and a failure fails the panel with the member's own code (SM-7, ans:Q23); unselected members count as resolved empty rows that the combine excludes. |
| SM-12 | Skip vs failure in the record | [proposed] | H×M | Given one skipped and one failed member, Then the combine call reads the `selection` context (the members' decision records): the skipped one is `excluded`/`not_selected` and listed in `skipped`; the failed one is `fail`/`missing` and counted in `dropped`. |
| SM-13 | NR-I4 extended | [proposed] | H×M | Given evidence with `not_selected` and no narrow record, Then it is valid only when every such member is in `skipped`; a member in `skipped` has `raw`, `value`, `score`, `weight` null; a `skipped` member is never chosen (CE-I3) and never in a narrow `kept`. |
| SM-14 | Narrow steps see selected members only | [implied] | M×M | Given `>> sf.Rank(k=1, by="conf") >> sf.Synthesize(m)`, Then Rank ranks only selected members that answered; a skipped member is not in the narrow live set (NR-I1 live set excludes `skipped`). |
| SM-15 | Model signal calls are refused with skip-Gate members (v1) | [proposed — review 3 F2] | H×M | Given a Fanout with a skip-Gate member and a block `sf.Judge`, a Gate fallback `sf.JudgePick` / `sf.Synthesize`, or any other step that makes its own model call over the panel, When the block is built, Then the SDK raises "sf.Judge and model fallbacks read every member; they are not supported with skip-Gate members in this version". Reason: those calls read the raw panel, which holds an empty row for each skipped member (`S/_evaluation/reducer_signals.py:132`); `selection` filters only inside the combine call. Signals the combine call computes from member replies (`sf.Verbalized`, `sf.Logprob`, `sf.Entropy`) stay allowed. |
| SM-16 | Declared signals on skipped members; Consistency refused | [implied — stated epic zero-call rule; proposed — review 3 F3] | H×M | Given `signals={"conf": sf.Logprob("prob")}`, Then a skipped member makes no logprob-carrying call and its `declared` values are null. Given `sf.Consistency(...)` in `signals=` of a Fanout with a skip-Gate member, Then the SDK raises "sf.Consistency is not supported with skip-Gate members in this version": the combine call reads samples by url4 reference, and a sample panel inside a gated body is not visible outside it (`S/_evaluation/candidate.py:793`). |
| SM-17 | Budget refuses a selected member; parallel overspend | [proposed — [budget](budget.md); stated ans:Q20] | M×M | Given a Budget and a selected member whose estimate would break the cap, Then that member's decision record has `budget_refused`, the member is in `skipped`, and the quorum floor counts it as not selected. Sibling members each check only their own ancestors, so three selected members can jointly pass the cap; the report shows that overspend. |
| SM-18 | Mixed members | [proposed] | M×M | Given a Fanout with two plain members and one skip-Gate member, Then the plain members always run; the quorum floor counts plain members plus selected skip-Gate members. |
| SM-19 | Same label on two members | [implied] | L×M | Given two skip-Gates that test `has("math")`, Then both run when `math` is selected. |
| SM-20 | `then=` holds a Gate | [stated ans:Q10] | L×L | Given a skip-Gate whose `then` is another Gate (inside a branch), Then it compiles under the depth cap of [branch-core](branch-core.md) BC-18. |
| SM-21 | Replay | [implied — GD-I6] | H×M | Given a captured run, When it replays, Then the selector reply comes from the cache, the same members are skipped, and the evidence bytes are equal. |
| SM-22 | Member cap | [proposed] | L×L | Given more than 256 members (`S/reducer.py:423`), Then the existing cap refuses the block before the skip rules run. |
| SM-23 | Model writer without a combine call | [proposed] | M×M | Given a block with skip-Gate members and `>> sf.Synthesize(m)` only, Then the compiler inserts the implicit selection combine call (SM-4), so the quorum floor (SM-11) and the `skipped` record exist for writer blocks too. |

Not applicable: cancel/resume (same as [branch-core](branch-core.md) BC-19); concurrent second
actor (one Case is one expression).

## 4. Non-functional requirements

- Calls: per Case, the selector costs at most one model call (LabelModel) or zero (Keywords); a
  skipped member costs zero calls [stated epic]. Model signal calls and `sf.Consistency` are
  refused with skip-Gate members in v1 (SM-15, SM-16).
- Overhead: one DECIDE + one OPEN + one JOIN per skip-Gate member (pure, local); target < 5 ms CPU
  per member at p99 [proposed].
- Observability: the report shows, per block, the selected and the skipped members and the calls
  avoided (NOT_RUN_ENTRY `model_calls`) [proposed — see [report](report.md)].
- Security: the selector reply is untrusted text; DECIDE reads only declared labels from it
  ([selectors](selectors.md)); `selection` holds only decision-record references [proposed].

## 5. Out of scope

- A `sf.Route` class or any other set-valued construct [stated ans:Q9].
- A Gate member with `otherwise=` [stated ans:Q10].
- A block `sf.Judge`, Gate model fallbacks and other model signal calls on a Fanout with skip-Gate
  members, and `sf.Consistency` with skip-Gate members (v1; SM-15, SM-16) [proposed — review 3
  F2, F3].
- Embedding top-k selection (PPRoute) [stated ans:Q4].
- A parallel race that cancels members once one succeeds [stated ans:Q5].
- A default member for "nothing selected" as its own feature: write a skip-Gate with
  `when=sf.labels(sel).empty()` ([selectors](selectors.md) SL-15) or an outer Gate [proposed].

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: outside-in on the compile shape, then the Engine record rules, because the zero-call
guarantee (SM-1, SM-10) is the risk this PRD exists for. RED first; GREEN minimal; refactor on
green. CHAR rows pin today's quorum panel behavior. Row #18 needs the budget and is built in PR-3
(plan unit 13).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `quorum_panel_leaves_a_failed_optional_member_missing` | integration | [existing `E/combine/endpoint.py:1339-1343`] | H×M | passes today |
| 2 | CHAR `gate_is_refused_as_a_fanout_member_today` | unit | [existing `S/recipe.py:138-145`] | M×M | passes today; row 5 changes it |
| 2a | PIN `declared_vocabulary_gains_quorum_not_met` (`ET/test_failure_classes.py` exact set; `ET/test_e4b_catalog_pins.py` count 67 → 68; `ET/test_terminal_error_detail.py` allowlist) | unit | SM-11 | H×M | owner-approved pinned edits (PR-2) |
| 2b | `quorum_not_met_is_declared_permanent_on_both_sides` (Engine helper; SDK mirror conformance) | unit | SM-11 | H×M | `E/benchmarks/failure_classes.py` helper; `S/_report_primitives.py` |
| 3 | `unselected_skip_member_makes_zero_calls` (Engine world; fake gateway counts per binding, incl. logprob-carrying member calls) | integration | SM-1, SM-16 | H×H | required (all) or `;optional` (numeric) slot + gated body |
| 4 | `unselected_slot_gives_an_empty_row_that_the_combine_excludes` (no failure in the Case; quorum all and numeric) | integration | SM-10 | H×H | JOIN returns `""`; `selection` exclusion; DECIDE outside the slot |
| 5 | `skip_gate_member_is_accepted_and_other_gate_members_are_refused` (parametrized SM-8 forms) | unit | SM-8 | H×H | `S/fusion.py` `_members` accepts a skip-Gate |
| 5a | `model_signal_calls_are_refused_with_skip_gate_members` (block Judge; JudgePick and Synthesize fallbacks) | unit | SM-15 | H×M | compile check in the Fanout block |
| 5b | `consistency_is_refused_with_skip_gate_members` | unit | SM-16 | H×M | compile check in the Fanout block |
| 6 | `selected_members_vote_and_skipped_member_is_excluded_not_selected` | integration | SM-2 | H×H | `_answer` reads `selection`; `_record_status` |
| 7 | `quorum_counts_selected_members_with_min_floor` (decision table: all / N ≤ selected / N > selected) | unit | SM-11 | H×H | Engine floor check for a numeric quorum (panel `quorum=0`); required slots for `"all"` |
| 8 | `selected_member_failure_under_quorum_all_fails_with_its_own_code` | integration | SM-7 | H×M | required slot; url4 fails the panel with the member's code (ans:Q23) |
| 9 | `skip_and_failure_are_told_apart_by_selection_context` | unit | SM-12 | H×M | context key `selection` |
| 10 | `evidence_not_selected_without_narrow_needs_skipped` (NR-I4 extended, both directions) | unit | SM-13 | H×M | `_check_narrow`, new `_check_skipped` |
| 11 | `multi_selector_runs_once_before_the_panel` | integration | SM-3, SM-9 | H×M | hoisted selector source |
| 12 | `nothing_selected_abstains_no_votes` | integration | SM-6 | H×M | existing empty-panel rule |
| 13 | `writer_block_gets_selection_envelope_of_selected_members` | integration | SM-4, SM-23 | H×M | implicit selection combine call |
| 14 | `replay_skips_the_same_members` | integration | SM-21 | H×M | — |
| 15 | `keywords_multi_selects_every_matching_label_without_a_call` | unit | SM-5 | M×M | — |
| 16 | `rank_after_skip_members_ranks_selected_members_only` | integration | SM-14 | M×M | NR-I1 live set |
| 17 | `skipped_member_logprob_and_verbalized_values_are_null` | integration | SM-16 | M×M | combine reads only selected rows |
| 18 | `budget_refused_member_is_skipped` | integration | SM-17 | M×M | after [budget](budget.md) lands (PR-3) |
| 19 | `mixed_plain_and_skip_members_floor` | unit | SM-18 | M×M | — |
| 20 | `skipped_member_record_has_null_raw_value_score_weight_signals` | unit | SM-2, SM-13 | M×M | record builder |
| 21 | `sdk_decodes_skipped_and_selection_round_trip` (SDK evidence decode + url4 rebuild) | unit | SM-2, SM-12 | M×M | `S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`, `S/url4.py` |
| 22 | `two_members_with_the_same_label_both_run` | integration | SM-19 | L×M | — |
| 23 | `skip_gate_then_holds_a_gate_under_the_depth_cap` | unit | SM-20 | L×L | — |
| 24 | `fanout_over_256_members_is_refused_first` | unit | SM-22 | L×L | existing cap |
| 25 | PIN `combine_evidence_v1_schema_gains_skipped` (owner-approved snapshot edit) | unit | erd §6 | M×M | `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` |

Pinned files (owner approval at build time): `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`
(`skipped`, NR-I4 text); likely `ET/test_combine_evidence_words.py`, `ST/test_evidence_words.py`
and `ST/test_frozen_record_fields.py` (evidence key lists and counts); `ST/public_surface_snapshot.json`
only if the Fanout signature text changes (it should not).

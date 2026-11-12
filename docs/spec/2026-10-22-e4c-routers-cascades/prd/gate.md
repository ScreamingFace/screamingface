# PRD: The general `sf.Gate` (public surface)

**Source:** epic OME-1291, ans:Q6 (Gate is the one branch construct), ans:Q9 (no `sf.Route`),
ans:Q10 (where a Gate sits), ans:Q12 (N-way = nested binary Gates) · **Priority:** P0 (PR-1)
**Lifecycle:** existing (characterize + delta): the E4b part 5/6 `sf.Gate` widens
**Owner:** unassigned
Paths: [erd §1, §4, §6, §7](../erd.md) · contracts: C1, C2, C6 · component:
[branch-core](branch-core.md) (runtime, records, not-run guarantee) · references:
[selectors](selectors.md) (`sf.label`, `sf.labels`), [budget](budget.md)
(`sf.budget.remaining()`), [skip-members](skip-members.md) (Gate as a Fanout member),
[cascade](cascade.md) (sugar over this Gate), [lazy-fallback](lazy-fallback.md) (the E4b
fallback branch)

## 1. Summary and user story

As a researcher, I want one construct, `sf.Gate(when=..., then=..., otherwise=...)`, that runs
`then` when a condition on the Case holds and `otherwise` when it does not, where each branch can
be a reducer step, a whole recipe or an outcome (`sf.abstain()`, `sf.fail()`), so that I can write a router, a cascade, a
guard or a budget choice with the same tool, and a branch that is not taken costs nothing.

## 2. Background and constraints

- "A model that appears in the recipe might not be called. The recipe decides, from the question
  or from a number on an answer already produced, and only the chosen work runs." [stated epic]
- `sf.Gate` becomes the general branch construct: `then=` and `otherwise=` may be whole recipes;
  `sf.Cascade` is sugar over nested Gates. [stated ans:Q6]
- ONLY `sf.Gate`: there is no `sf.Route` class. [stated ans:Q9]
- A Gate may be the whole candidate, a Pipeline stage, or inside a branch; it is not a Fanout
  member, except the skip-Gate of ans:Q16. [stated ans:Q10, ans:Q16]
- An N-way choice is nested binary Gates:
  `Gate(when=sf.label(sel) == "math", then=..., otherwise=Gate(...))`; the selector value is
  computed once and shared. [stated ans:Q12]
- The condition is data, "not a Python function that only runs on the author's laptop".
  [stated epic]
- A branch that is not selected makes zero calls; the runtime, the records and the guarantee are
  in [branch-core](branch-core.md). [stated epic; stated ans:Q1]
- Messages follow MSG-1: the new surface names only, the article "a sf.", never "an sf."
  (`ST/test_surface_messages.py:1`, `:544`) [existing].

### 2.1 Current behavior

- `sf.Gate` is a `Step` with `_category = "reduce"` (`S/_surface/gate.py:28-48`) [existing]. It
  closes a Fanout block; it cannot be a recipe: `refuse_step` raises "sf.Gate is a step, not a
  recipe: put it after a sf.Fanout" for any step in a recipe position
  (`S/_surface/chain.py:84-100`) [existing].
- `when=` takes a `GateCondition` (`S/_surface/refs.py:97-106`) built from a `GateRef`
  (`:50-95`): `sf.agreement()` (`:120-123`), `sf.signal(x).chosen()`, `sf.signal(x).mean()`
  [existing]. An agreement condition takes only `>=` or `>` with a share in [0, 1]
  (`S/gate.py:152-161`) [existing].
- `then=` takes only a `sf.Vote` whose `over=` is a rule name: "sf.Gate then= takes sf.Vote until
  E4c" (GA-3, `S/_surface/gate.py:86-88`) and "a gated vote reads a rule name in over= until E4c"
  (GA-6, `:89-91`) [existing].
- `otherwise=` takes `"abstain"` (default), a `sf.JudgePick` or a one-model `sf.Synthesize`
  (`S/_surface/gate.py:95-109`); `abstain_if=ref.between(lo, hi)` must read the `when` number
  (`:112-120`) [existing].
- The docstring says the `otherwise` call "runs on every Case ... E4c will skip it"
  (`S/_surface/gate.py:44-45`) [existing].
- Lowering: `_gate_node` builds `VoteNode(..., gate=GateNode(observe, cmp, threshold,
  otherwise=, abstain_band=))` (`S/_surface/lowering.py:210-223`; `S/gate.py:39-75`)
  [existing]. The combine spec `gate` object is `{"cmp", "observe", "otherwise", "threshold"}`
  plus an optional band (`S/gate.py:77-89`) [existing].
- The Engine accepts a `gate` only on a vote: "only a vote takes a gate"
  (`E/combine/spec.py:445-446`) [existing].
- Recipe kinds are `model | fusion | pipeline | corrective_loop | self_corrective`
  (`S/recipe.py:107-136`); `_is_supported_recipe` admits `Model | FusionNode | Pipeline`
  (`:138-145`) [existing].
- Rebuild: `Url4.to_python()` (`S/url4.py:112`) decodes the candidate (`:140`), rebuilds the node
  (`S/_surface/rebuild.py:99-111`), turns a gated `VoteNode` into `Gate` (`:318-331`) and checks
  that the value recompiles to the same url4 (RB-1, `:108-110`) [existing]. `_rebuilt_gate`
  checks that the spec `otherwise` word and the fallback call agree (`S/reducer.py:632-666`)
  [existing]. The repr shows `when`, `then`, a non-default `otherwise` and the band
  (`S/_surface/render.py:236-242`) [existing].
- `_PROVED_SPEC_KEYS = {"signals", "narrow"}` (`S/url4.py:92`): a hand-added `gate` key does not
  force the byte recompile check [existing].
- `budget.remaining` is a reserved key that the signal parser refuses ("E4c compares read")
  (`S/_signals.py:55-58`) [existing].

Delta (this PRD):

1. One public class `sf.Gate` with two forms. The form follows from `when=` [proposed]:
   - **Panel gate**: `when` reads `sf.agreement()`, `sf.signal(x).chosen()`,
     `sf.signal(x).mean()` or `sf.answered()` ([cascade](cascade.md)). It closes a Fanout block,
     as today. A bare `sf.signal(x) <op> v` reads the chosen member, the same as
     `sf.signal(x).chosen() <op> v`, and the record names `chosen:x` [stated owner 2026-11-12].
   - **Input gate**: `when` reads `sf.label(sel) == / != "x"`, `sf.labels(sel).has("x")` or
     `.empty()` ([selectors](selectors.md)) or `sf.budget.remaining()` ([budget](budget.md)). It is a recipe: the root, a Pipeline stage, or
     a branch body.
2. `then=` is required; `otherwise=` defaults to the sentinel `None`: `sf.abstain()` for a Gate at
   the root, in a Pipeline stage or in a branch, and "skip" for a skip-Gate Fanout member
   ([skip-members](skip-members.md)). So the SDK can tell an omitted `otherwise=` from an explicit
   `sf.abstain()`; "skip" is never a public value [proposed — review finding 9]. Each takes
   [stated ans:Q6]:
   a **step** (panel gate only): `sf.Vote`, `sf.Median`, `sf.Mean`, `sf.ArgMax`, `sf.ArgMin`,
   `sf.First`, `sf.Merge`, `sf.JudgePick`, `sf.Synthesize`; a **recipe**: a model route, `sf.Model`,
   a closed chain or Pipeline, another input `sf.Gate`, a `sf.Cascade` value; an **outcome**:
   `sf.abstain()` or `sf.fail()`. The SDK stores the words `"abstain"` and `"fail_closed"` inside,
   so the compiled bytes, the records and the codes (`gate_not_met`, `no_votes`, `fail_closed`) do
   not change. The string `"abstain"` still works (the E4b spelling, released in v0.1.12); the
   string `"fail_closed"` is refused (GT-12). `repr` and `to_python` print `sf.abstain()` and
   `sf.fail()` [stated owner 2026-11-12 — supersedes the words `"abstain"` / `"fail_closed"` as
   the public spelling].
3. GA-3, GA-6 and the D5 "then= is Vote only" rule go away; the "until E4c" text goes away from
   every message and docstring [stated ans:Q6].
4. New internal node `BranchNode` (recipe kind `gate`) for every Gate; a panel gate keeps the E4b
   `GateNode` on its decision reducer for the combine `gate` record [proposed].
5. The Engine accepts a `gate` on any reducer, with the observe rules of §3.1 GT-6
   ([branch-core](branch-core.md) D4) [proposed].
6. `_PROVED_SPEC_KEYS` gains `"gate"` [proposed].
7. The decision call writes combine `gate.otherwise` = `judge` / `writer` for an E4b fallback step
   and `abstain` for every other `otherwise`; DECIDE maps the panel branch by the table of
   [branch-core](branch-core.md) D4: `majority` → `then`, `fallback` → `otherwise`, a band hit →
   no branch and abstain `in_band`, no voters → `otherwise` only when it is a recipe and the
   condition is `sf.answered()` (an `sf.escalate_if(sf.unanswered())` line), else no branch and the
   decision call's abstain; with a recipe `then`, a band hit or no votes never runs `then`
   [proposed; stated ans:Q25; stated owner 2026-11-12 — supersedes "no voters → a recipe
   `otherwise`" for every condition].
9. A recipe `otherwise` runs only when the comparison is false. A missing number with a recipe
   `otherwise` fails the Case with the new code `signal_missing` (branch-core D4a, GT-29); every
   other `otherwise` keeps the E4b missing-number fallback. Nothing falls back unless the recipe
   says so [stated owner 2026-11-12].
8. A Gate inside a `sf.CorrectiveLoop` / `sf.SelfCorrective` member, judge or coach, or a
   CorrectiveLoop as a Gate branch, is refused at compile time: the loop runs its members in an
   isolated recorder [existing `E/world/corrective.py:104-110`], so budget and attribution would
   break [stated ans:Q26].

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **GT-1 Input gate as the candidate.** Given
  `sf.Gate(when=sf.label(kw) == "math", then=math_panel, otherwise="prov/general")`, When it is
  the candidate, Then it compiles to one Gate (branch-core shape), the Case runs `math_panel` or
  `prov/general`, and the other branch makes zero calls. [stated epic; stated ans:Q6]
- **GT-2 Panel gate with a recipe branch.** Given
  `sf.Fanout([a, b, c]) >> sf.Gate(when=sf.agreement() >= 0.8, then=sf.Vote(),
  otherwise="prov/large")`, When the panel agrees, Then the vote answers and `prov/large` makes no
  call; else `prov/large` answers the Gate's input and the vote's answer is not the output.
  [stated epic behavior 2; stated ans:Q6]
- **GT-3 Any reducer step in `then=`.** Given `then=sf.Median()` with
  `when=sf.signal("conf").mean() >= 0.8`, When the condition holds, Then the median answers.
  The old GA-3 refusal no longer exists. [stated ans:Q6]
- **GT-4 Outcomes.** Given `then=sf.fail()` or `otherwise=sf.abstain()`, When that branch is
  taken, Then the Case fails with `fail_closed` or abstains with `gate_not_met` (branch-core BC-8,
  BC-9). `otherwise="abstain"` gives the same bytes as `otherwise=sf.abstain()`. [stated epic;
  stated owner 2026-11-12]
- **GT-5 N-way by nesting.** Given
  `Gate(when=sf.label(sel) == "math", then=m, otherwise=Gate(when=sf.label(sel) == "code",
  then=c, otherwise=g))`, When the selector returns `code`, Then only `c` runs, the selector runs
  once (selectors PRD SL rows), and the outer and inner records each list their not-run branch.
  [stated ans:Q12]
- **GT-6 Panel decision reducer.** Given a panel gate, When it compiles, Then its decision is the
  block's one combine call with a `gate` object, and that call's reducer is: `then` when `then`
  is a reducer step; else `otherwise` when it is a reducer step; else an implicit decision-only
  `Vote(over="last_line")` whose output no branch reads. `sf.agreement()` needs a vote as the
  decision reducer; `chosen:<name>` needs a reducer that chooses one member (`Vote`, `ArgMax`,
  `ArgMin`, `First`, `JudgePick`) or the implicit vote; `mean:<name>` takes any reducer.
  [proposed — [branch-core](branch-core.md) D4]
- **GT-7 Pipeline stage.** Given `sf.Gate(...) >> "prov/aggregator"`, When it runs, Then the
  aggregator gets the taken branch's answer ("Experts are all you need": route, then always
  write). [stated ans:Q10; stated epic]
- **GT-8 Branch input.** Given a recipe branch, When it runs, Then its input is the input the Gate
  itself received: the Case input for a root Gate, a first Pipeline stage, and a panel gate of a
  first block; the previous stage's answer for a Gate that is a later Pipeline stage (the
  Pipeline rule). A Cascade stage therefore always answers the original question.
  [stated epic; implied — branch-core BC-5]
- **GT-9 Repr and `to_python`.** Given a 3-way nested Gate, When I print it or call
  `Url4(...).to_python()`, Then the output is the source form: one `sf.Gate(` per level,
  `otherwise=sf.Gate(` indented one level deeper per nesting step, `otherwise=` left out when it
  was omitted (the sentinel), and the text compiles back to the same url4 (RB-1). [proposed]
- **GT-10 The band stays.** Given a panel gate with `abstain_if=ref.between(lo, hi)`, When the
  number is in the band, Then the Case abstains with `in_band` for every `otherwise`, as in E4b
  part 6, and no branch body runs, also when `then=` is a recipe; the same holds when the panel
  produced no votes and `otherwise` is not a recipe, or is a recipe under any condition but
  `sf.answered()` (abstain `no_votes`, GT-28). [existing `S/_surface/gate.py:112-120`; stated
  ans:Q25; stated owner 2026-11-12]
- **GT-28 No answer with a recipe `otherwise` does not escalate.** Given
  `sf.Fanout([a, b]) >> sf.Gate(when=sf.agreement() >= 0.8, then=sf.Vote(),
  otherwise="prov/large")`, When the vote abstains (`no_votes`, `cut_not_met`, `output_missing`),
  Then `prov/large` makes zero calls and the Case abstains with the vote's reason. Only a gate whose
  condition is `sf.answered()` sends a null branch to its recipe `otherwise` ([cascade](cascade.md)
  CA-10). [stated owner 2026-11-12 — supersedes ans:Q17 for every Gate]
- **GT-29 Missing number with a recipe `otherwise`.** Given
  `sf.Fanout([small], signals={"lp": sf.Logprob("prob")}) >> sf.Gate(when=sf.signal("lp") >= 0.7,
  then=sf.Vote(), otherwise="prov/large")`, When the reply carries no log-probability, Then
  `prov/large` makes zero calls and the Case fails with `signal_missing` ("sf.Gate gate_N read a
  missing number, so it can neither keep the answer nor escalate"). With `otherwise=sf.abstain()`,
  a `sf.JudgePick` or a `sf.Synthesize`, the E4b missing-number fallback is unchanged.
  [stated owner 2026-11-12; branch-core D4a, BC-39]

### 3.2 Error paths

- **GT-11 A step needs a panel.** Given an input gate with `then=sf.Vote()`, Then the
  constructor raises `ValueError("a step in then= needs a panel: put the sf.Gate after a
  sf.Fanout, or give a recipe")`. [proposed]
- **GT-12 Wrong branch value.** Given `then=42`, `otherwise="skip"` (anywhere: "skip" is not a
  public value), or the string `"fail_closed"` (or another spelling of a word, such as
  `"fail-closed"`, `"ABSTAIN"`, `"fail"`), Then the constructor raises `TypeError("sf.Gate then=
  takes a step, a recipe, sf.abstain() or sf.fail()")` (the same text with `otherwise=`). A word
  spelled another way is a typo, never a model route. [proposed; stated owner 2026-11-12 — the
  string `"fail_closed"` is now refused; write `sf.fail()`]
- **GT-13 Wrong condition.** Given `when=sf.signal("x")` or a Python function, Then
  `TypeError("sf.Gate when= takes a condition such as sf.agreement() >= 0.7, sf.label(sel) ==
  'x' or sf.budget.remaining() >= 0.02")`. [existing message widened `S/_surface/gate.py:62-66`;
  stated epic]
- **GT-14 Panel ref on an input gate.** Given `sf.Gate(when=sf.agreement() >= 0.8, ...)` used as
  the candidate (no Fanout before it), Then the compile raises "sf.agreement() reads a panel: put
  the sf.Gate after a sf.Fanout". [proposed]
- **GT-15 Gate as a Fanout member.** Given `sf.Fanout([a, sf.Gate(...)])` where the Gate was
  given any `otherwise=` (an explicit `sf.abstain()` included), Then `ValueError("a sf.Gate is not a
  sf.Fanout member; a member Gate takes no otherwise= (skip members)")`. The sentinel `None`
  tells the omitted value apart. [stated ans:Q10; stated ans:Q16]
- **GT-16 Decision reducer mismatch.** Given a panel gate with `when=sf.agreement() >= 0.8` and
  `then=sf.Median()`, Then the constructor raises "sf.agreement() needs a sf.Vote in then= or
  otherwise=, or no reducer step at all". [proposed — GT-6]
- **GT-27 Gate and CorrectiveLoop.** Given `sf.CorrectiveLoop(members=[gate_recipe, m2], judge=j)`,
  a loop whose judge is a Gate, or `sf.Gate(when=…, then=sf.CorrectiveLoop(...))`, When it
  compiles, Then it raises `ValueError("a sf.Gate cannot sit inside a sf.CorrectiveLoop, and a
  sf.CorrectiveLoop cannot be a sf.Gate branch")` before any run. [stated ans:Q26]

### 3.3 Derived scenarios

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| GT-17 | E4b gate bytes stay | [implied — E4b C8] | H×H | Given every E4b part 5/6 gate recipe (`ST/data/surface_parity.json` gate rows), When it compiles after this PRD, Then the combine spec and evidence bytes are unchanged; only the gated-iterate shape is added around it (lazy-fallback PRD). |
| GT-18 | Rebuild refuses a hand-edited mismatch | [proposed — gap §per-connection/data] | H×M | Given a url4 whose gate spec says `otherwise: "recipe"` but whose otherwise iterate body is empty, When `to_python()` runs, Then it raises "cannot rebuild" (RB-1), never a guessed recipe. |
| GT-19 | Hand-added gate forces recompile | [proposed — gap §replay] | H×M | Given a plain url4 with a hand-added combine `gate` key and no `signals`/`narrow`, When the SDK reads it, Then the recompile check runs (`_PROVED_SPEC_KEYS` has `gate`). |
| GT-20 | Engine gate on a median | [proposed] | H×M | Given a combine spec `{"reducer": "median", "gate": {"observe": "mean:conf", ...}}`, When the Engine parses it, Then it accepts it; an `agreement` gate on a non-vote reducer raises "an agreement gate needs a vote". |
| GT-21 | Equality and hash | [existing `ST/test_gate_surface.py:191`] | M×M | Given two Gates with equal bytes, Then they are equal; a Gate stays unhashable (it may hold a `sf.Model`). |
| GT-22 | Deep N-way repr | [proposed] | M×M | Given an 8-level nested Gate, Then `repr` and `to_python()` finish in linear time and stay one Gate per line in `code()` layout. |
| GT-23 | Same selector, two instances | [proposed — gap §per-flow/repeat] | M×M | Given two equal `sf.RegexClassifier(...)` values in two nested Gates, Then they compile to one selector id (equal bytes = one instance), so the Case evaluates it once. |
| GT-24 | Cascade value in a branch | [stated ans:Q10] | M×L | Given `otherwise=sf.Cascade(t1, sf.escalate_if(c), t2)`, Then the compile nests the Cascade's Gates inside the branch body. |
| GT-25 | Outcomes in both branches | [proposed — gap §boundary] | L×L | Given `then=sf.abstain(), otherwise=sf.fail()`, Then it compiles; a Case takes one outcome and the record shows the other as not run. |
| GT-30 | Typed outcomes keep the bytes | [stated owner 2026-11-12] | H×M | Given `sf.abstain()` / `sf.fail()` in a branch, Then the compiled url4 equals the url4 of the stored words `"abstain"` / `"fail_closed"`, and `repr` / `to_python()` print `sf.abstain()` / `sf.fail()`; the rebuilt text recompiles to the same bytes (RB-1). |
| GT-26 | Concurrent sibling Gates | [implied] | L×M | N/A at the surface: two Gates in one Case share no state (branch-core BC-20). Listed so no one adds shared state here. |

## 4. Non-functional requirements

- Constructor validation runs at `sf.Gate(...)` and at the `>>` that closes a block, before any
  run, so a wrong Gate never spends money [proposed].
- `repr` / `to_python` cost is linear in the number of Gates [proposed].
- Messages never echo a prompt, a rubric or a label pattern; they name the argument and the rule
  [existing rule `S/gate.py:190`].

## 5. Out of scope

- A `sf.Route` class or a `cases=` form [stated ans:Q9, ans:Q12].
- Gate as a general Fanout member [stated ans:Q10]; the skip-Gate is in
  [skip-members](skip-members.md) [stated ans:Q16].
- The selector values and the budget ref themselves ([selectors](selectors.md),
  [budget](budget.md)).
- The E4b fallback skip mechanics ([lazy-fallback](lazy-fallback.md)).
- A Gate inside a CorrectiveLoop, or a CorrectiveLoop as a Gate branch (refused, GT-27)
  [stated ans:Q26].

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: outside-in. The surface checks first (cheap, no Engine), then lowering and compile bytes,
then the Engine spec rule, then rebuild, because the surface is what the user writes and every
later row reads its values. CHAR rows pin the E4b gate first. PIN rows are owner-approved edits of
pinned tests.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `e4b_gate_recipes_compile_to_the_bytes_of_today` (`ST/test_gate_surface.py:184`) | unit | GT-17 | H×H | passes today |
| 2 | CHAR `gate_equality_follows_the_bytes` (`ST/test_gate_surface.py:191`) | unit | GT-21 | M×M | passes today |
| 3 | CHAR `band_abstains_for_every_otherwise` (E4b part 6 rows) | unit | GT-10 | H×M | passes today |
| 4 | `panel_gate_otherwise_takes_a_recipe` | unit | GT-2 | H×H | `_branch()` value check in `S/_surface/gate.py` |
| 5 | `input_gate_is_a_recipe_at_the_root` (`_recipe_kind` → `gate`, `_is_supported_recipe` true) | unit | GT-1 | H×H | `S/recipe.py:107-145`; `BranchNode` |
| 6 | `gate_compiles_to_decide_open_join` (url4 shape, branch-core §3.2) | unit | GT-1 | H×H | `BranchNode` lowering → renderer |
| 7 | PIN `ST/test_gate_surface.py:316-319` GA-3 test becomes `then_takes_any_reducer_step` | unit | GT-3 | H×H | owner approval; remove GA-3 |
| 8 | PIN `ST/test_gate_surface.py:375-379` GA-6 test becomes `gated_vote_takes_an_extractor` | unit | GT-3 | H×M | owner approval; gate on `ReduceNode` |
| 9 | `outcomes_fail_and_abstain_compile` (and the string `"abstain"` gives the same bytes) | unit | GT-4 | H×H | word bodies; `S/_surface/outcomes.py` |
| 10 | `step_in_an_input_gate_is_refused` | unit | GT-11 | H×M | form check |
| 11 | `panel_ref_without_a_fanout_is_refused` | unit | GT-14 | H×M | compile check |
| 12 | `gate_with_otherwise_as_a_fanout_member_is_refused` (explicit `sf.abstain()` included) | unit | GT-15 | H×M | `refuse_step` admits only the skip-Gate; sentinel default |
| 13 | `wrong_branch_value_names_the_four_kinds` (parametrized: 42, "skip" at the root and as a member, "fail_closed", a step class) | unit | GT-12 | M×M | messages, MSG-1 article |
| 14 | `when_takes_a_condition_message_lists_three_examples` | unit | GT-13 | M×M | message widened |
| 15 | `decision_reducer_is_then_else_otherwise_else_implicit_vote` (decision table) | unit | GT-6 | H×H | `_decision_reducer()` |
| 16 | `agreement_gate_needs_a_vote` | unit | GT-16 | H×M | constructor check |
| 17 | `engine_accepts_a_gate_on_a_median_with_mean_observe` | unit | GT-20 | H×M | `E/combine/spec.py` `_check_gate` widened |
| 18 | PIN `ET/test_combine_gate_words.py:397-403` GR#4 becomes `agreement_gate_needs_a_vote_reducer` | unit | GT-20 | H×M | owner approval |
| 19 | `nested_three_way_gate_runs_only_the_selected_branch` (Engine world, fake gateway) | integration | GT-5 | H×H | nested iterate |
| 20 | `pipeline_stage_after_a_gate_gets_the_taken_answer` | integration | GT-7 | H×M | Pipeline rule |
| 21 | `branch_input_is_the_gate_input` (root, first stage, later stage, panel gate) | integration | GT-8 | H×H | `_capture_recipe(input_context=<gate input>)` |
| 22 | `to_python_round_trips_a_three_way_gate` | unit | GT-9 | H×M | `S/_surface/rebuild.py` `_branch`; `render._gate` nested layout |
| 23 | `rebuild_refuses_a_spec_body_mismatch` | unit | GT-18 | H×M | `_rebuilt_branch` checks word vs body |
| 24 | `hand_added_gate_key_forces_recompile` | unit | GT-19 | H×M | `S/url4.py:92` adds `gate` |
| 25 | `equal_selectors_in_nested_gates_share_one_id` | unit | GT-23 | M×M | selector id by bytes |
| 26 | `cascade_value_nests_in_a_branch` | unit | GT-24 | M×L | — |
| 27 | `eight_level_repr_is_linear_and_one_gate_per_line` | unit | GT-22 | M×M | render layout |
| 28 | PIN `ST/test_gate_surface.py:432-437` docstring test: says the not-taken branch makes no call, no "E4c" | unit | §2.1 delta 3 | M×M | owner approval; docstring rewrite |
| 29 | PIN `ST/public_surface_snapshot.json` `Gate.__init__` signature (`then: 'Branch'`, `otherwise: 'Branch \| None' = None`) | unit | delta 1–2 | M×M | owner approval; regenerate snapshot |
| 30 | `messages_name_the_new_surface_only` (MSG-1 still green with the new messages) | unit | §2 | M×M | `ST/test_surface_messages.py` runs unchanged |
| 31 | `outcomes_in_both_branches_compile` | unit | GT-25 | L×L | — |
| 33 | `null_branch_with_a_recipe_otherwise_abstains_unless_answered` (Engine world, fake gateway: `prov/large` makes zero calls) | integration | GT-28 | H×H | branch-core D4 null rows |
| 34 | `missing_number_with_a_recipe_otherwise_fails_with_signal_missing` | integration | GT-29 | H×H | branch-core D4a |
| 35 | `typed_outcomes_compile_to_the_word_bytes_and_print_typed` | unit | GT-30 | H×M | `outcome_text`; render and rebuild |
| 32 | `gate_and_corrective_loop_nesting_is_refused` (Gate as a loop member, judge or coach; loop as a Gate branch) | unit | GT-27 | M×L | compile check in `_is_supported_recipe` / renderer |

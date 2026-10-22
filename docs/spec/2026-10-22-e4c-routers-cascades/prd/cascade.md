# PRD: Cascade — cheap first, escalate only when a signal is weak

**Source:** epic OME-1291 behavior 2, ans:Q6, ans:Q7, ans:Q17, OME-1465, OME-1630
· **Priority:** P0 (PR-1)
**Lifecycle:** planned (a new public shortcut function over [gate](gate.md))
**Owner:** unassigned
Paths: [erd §1, §3, §4](../erd.md) · contracts: C1–C4 · component: [branch-core](branch-core.md),
[gate](gate.md) · budget interplay: [budget](budget.md) · display: [report](report.md)

## 1. Summary and user story

As a researcher whose result is a saving, I want to write "run the cheap stage; call the next
stage only when the cheap stage's signal is weak or the cheap stage did not answer", so that the
expensive model runs only on the Cases that need it, and the report shows the share of Cases that
stayed on the cheap stage.

`sf.Cascade([s1, s2, …, sn], escalate_if=cond, otherwise=None)` is a shortcut function. It returns
ordinary nested `sf.Gate` values (ans:Q6), the way `sf.Fusion` returns the `sf.Fanout(...) >> S`
chain. It has no compile path of its own.

## 2. Background and constraints

- "Run the first stage. Compute a declared comparison. If it passes, return that stage's answer
  and do not call the later stages. If it fails, call the next stage on the original question,
  not on the previous answer. Repeat until a stage passes or the list ends." [stated epic]
- "Stage 1 always runs." "Stage k+1 runs only if stage k's escalate condition is true." [stated epic]
- "Each stage's prompt input is the original user question (plus whatever the recipe attaches),
  not 'here is the previous model's answer, please continue.'" [stated epic]
- "The condition is a comparison the author wrote against a declared signal: `confidence < 0.7`,
  `agreement < 0.8`. It is data." [stated epic]
- "The signal is E4b. This epic does not define how confidence is measured. It defines the skip."
  [stated epic]
- "Human as the last tier: if every model tier escalates, the outcome is abstain, not a made-up
  answer. The report counts it as declined." [stated epic]
- STEER: "v1 is per full answer. Per-token escalation inside a single decode is out of scope."
  [stated epic]
- Cascade is sugar over nested Gates. [stated ans:Q6]
- Adaptive sampling is a Cascade over sample panels; no sample reuse; documented; the incremental
  top-up stays OME-1630. [stated ans:Q7]
- A stage that fails or abstains escalates; `sf.Cascade` marks its stage members optional and
  compiles each gated stage's panel with url4 `quorum=0`, the consistency precedent [existing
  `S/_evaluation/candidate.py:761-800`]; only the last stage's failure fails the Case.
  [stated ans:Q17] This holds for `otherwise=None`; with `otherwise="abstain"` or `"fail_closed"`
  the last stage is gated too and a last stage with no voters follows the word (CA-30).
- A gated stage where only some members fail decides on the members that answered; only "no
  member answered" escalates by itself. [stated ans:Q24]
- Today `quorum="all"` compiles to url4 `quorum = len(members)` [existing
  `S/_evaluation/candidate.py:403`]; a failed optional slot does not count, and below the quorum
  url4 raises `QUORUM_NOT_MET` for the whole group [existing `U/dag/nodes/_shared.py:221-224`,
  `:255-261`]. So optional members alone cannot make a stage escalate.
- OME-1465: "an early-termination mode where the first member/branch to succeed 'trumps' the
  others and the remaining branches are not run"; sequential form only. [stated ans:Q5]
- OME-1630: "early-stopping and dynamic reallocation of samples/compute based on intermediate
  results"; via a Cascade over sample panels. [stated ans:Q7]

### 2.1 Current behavior (the pieces the shortcut reuses)

- `sf.Fusion` is a function that returns the ordinary chain; "no second compile path: the result
  is the chain that `sf.Fanout(members, ...) >> S` builds, so it compiles to the same bytes"
  (`S/_surface/fusion.py:1-8`, `:33-64`) [existing]. This PRD copies that pattern.
- `sf.Gate(when=, then=, otherwise=, abstain_if=)` closes a block; `then` must be a `sf.Vote`
  "until E4c" (`S/_surface/gate.py:86-92`) [existing]; [gate](gate.md) widens it (ans:Q6).
- A gate condition is `GateRef <cmp> threshold`, cmp in `>=`, `>`, `<=`, `<`
  (`S/_surface/refs.py:50-95`). The stored form is the KEEP form: the condition that keeps the
  answer; an agreement gate accepts only `>=` or `>` with a threshold in [0, 1]
  (`S/gate.py:152-161`) [existing].
- `passes(None, cmp, threshold)` is False (`E/combine/gate.py:73-75`): a missing number takes the
  fallback branch [existing].
- `sf.Fanout(members, signals=, quorum=, name=, prompt=)`; a member may be `optional=True`
  (`S/_surface/fanout.py:24-60`; `S/model.py:26-43`) [existing]. `quorum` is the successful-member
  floor, `"all"` or 0..n (`S/fusion.py:399-405`) [existing].
- `sf.samples(model, n, seeds=None, …)` builds n Models that differ in `seed`; the default seeds
  are `0..n-1` (`S/_samples.py:21-51`, `:62-75`) [existing].
- No `sf.Cascade` exists [existing].

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **CA-1 The shortcut builds nested Gates.** Given `sf.Cascade([s1, s2, s3], escalate_if=c)` where
  `s1 = sf.Fanout(A) >> sf.Vote()` and `s2 = sf.Fanout(B) >> sf.Vote()`, When it is built, Then the
  result equals `sf.Fanout(A') >> sf.Gate(when=keep(c), then=sf.Vote(), otherwise=sf.Fanout(B') >>
  sf.Gate(when=keep(c), then=sf.Vote(), otherwise=s3))`, where `A'`, `B'` are the members marked
  optional with the stage panel at url4 `quorum=0` (CA-6). `==`, `repr` and `Url4.to_python()`
  show this Gate form. [stated ans:Q6;
  proposed — `S/_surface/fusion.py` exemplar]
- **CA-2 Stage 1 passes: later stages make zero calls.** Given stage 1's condition holds, When the
  Case runs, Then the answer is stage 1's reducer answer, stages 2..n make zero model calls, and
  the outer Gate's decision record lists `otherwise` as `not_selected`. [stated epic]
- **CA-3 Escalation answers the original question.** Given stage 1's condition fails, When stage 2
  runs, Then stage 2's members receive the Cascade's input (the Case input when the Cascade is the
  root or a first stage) and never stage 1's answers. [stated epic; branch-core BC-5]
- **CA-4 Polarity.** Given `escalate_if = ref < x`, Then the Gate keeps with `ref >= x`; `<=` →
  `>`; `>` → `<=`; `>=` → `<`. The decision record and the report show the author's escalate form
  next to the stored keep form. [proposed — `S/_surface/refs.py` keep form, E4b P4]
- **CA-5 Per-stage conditions.** Given `escalate_if=[c1, c2]` for three stages, Then stage k's Gate
  reads `ck`; a single condition applies to every gated stage. [proposed]
- **CA-6 Failure escalates.** Given a gated stage whose members all fail (refusal, token cap), When
  the Case runs, Then the url4 panel does not fail (its quorum is 0), the decision call finds no
  voters and abstains `no_votes` before the gate (E4b gate branch null), and DECIDE maps the null
  branch to `otherwise` because the next stage is a recipe ([branch-core](branch-core.md) D4): the
  next stage runs and the Case does not fail. `sf.Cascade` builds every gated stage's members with
  `optional=True` and its panel with url4 `quorum=0`. [stated ans:Q17; existing
  `S/_evaluation/candidate.py:761-800` precedent]
- **CA-29 Partial failure decides on the rest.** Given a gated stage of three members where one
  fails and two answer, When the Case runs, Then the decision call reduces over the two answers
  (agreement over 2 votes, the mean over their signals) and the gate compares as usual; the stage
  escalates only when that comparison fails. [stated ans:Q24]
- **CA-7 Abstain escalates.** Given a gated stage whose reducer abstains (`no_votes`, `cut_not_met`,
  `output_missing`), When the Case runs, Then the gate did not run (`branch` null in the E4b gate
  record), and the next stage runs: the null-branch rule of [branch-core](branch-core.md) D4 maps a
  null panel branch to `otherwise` when `otherwise` is a recipe body (the next stage). [stated
  ans:Q17; proposed — branch-core D4]
- **CA-8 Last stage answers unconditionally by default.** Given `otherwise=None` (default), Then the
  last stage is any recipe (a route string, `sf.Model`, chain, Gate) and its answer is final; its
  failure fails the Case. [stated ans:Q17; proposed default]
- **CA-9 Human as the last tier.** Given `otherwise="abstain"`, Then the last stage is gated too, and
  when its condition fails the Case abstains with `gate_not_met`, scored 0 and counted as declined.
  The innermost JOIN writes the abstain and every outer JOIN copies it from its `otherwise`
  terminal, so it reaches the root ([branch-core](branch-core.md) D12, BC-36). [stated epic;
  proposed — erd §6 reason reuse; review 3 F1]
- **CA-30 All members of a gated last stage fail.** Given `otherwise="abstain"` or
  `"fail_closed"` and a last stage whose members all fail, When the Case runs, Then the decision
  call finds no voters (url4 `quorum=0`, CA-6), the E4b gate branch is null, and the branch-core D4
  null row applies: with `"abstain"` the Case abstains `no_votes` (scored 0, declined); with
  `"fail_closed"` JOIN raises `fail_closed` and the Case fails with that code. It never fails with
  a member's code. "Only the last stage's failure fails the Case" holds for `otherwise=None` only
  (CA-19). [proposed — review 3 F7]
- **CA-10 First-success (OME-1465, sequential).** Given `escalate_if=None`, Then each gated stage
  escalates only when it fails or abstains: `sf.Cascade(["prov/a", "prov/b", "prov/c"])` returns the
  first stage's answer that exists; later stages make zero calls. A route string or `sf.Model` stage
  becomes `sf.Fanout([m]) >> sf.Vote()`, and its output is the member reply byte for byte.
  [stated ans:Q5; proposed `sf.answered()` condition, §6 cross-PRD]
- **CA-11 Adaptive sampling (ans:Q7).** Given `sf.Cascade([sf.Fanout(sf.samples(m, 2)) >> sf.Vote(),
  sf.Fanout(sf.samples(m, 5, seeds=range(2, 7))) >> sf.Vote()], escalate_if=sf.agreement() < 1.0)`,
  Then two samples run on every Case and five fresh samples run only when the two disagree; the
  escalated Case pays 2 + 5 calls; stage 2 does not reuse stage 1's samples. The docs state this
  and point to OME-1630 for the incremental top-up. [stated ans:Q7]

### 3.2 Error paths (refused when the shortcut is called, before any run)

- **CA-12 Fewer than two stages.** `sf.Cascade([s1])` or `[]` → `ValueError("sf.Cascade needs at
  least two stages")`. [proposed]
- **CA-13 A gated stage that is not a block ending in a reducer step.** A gated stage that is a
  route string or `sf.Model` (with `escalate_if` given), a Fanout with no reducer, a chain that ends
  in `sf.Synthesize`, or a narrow step at the end → `TypeError("a cascade stage before the last must
  end in a reducer step such as sf.Vote(): write sf.Fanout([m], signals=...) >> sf.Vote()")`.
  [proposed]
- **CA-14 Undeclared signal.** `escalate_if=sf.signal("conf").chosen() < 0.7` on a stage whose
  Fanout does not declare `conf` → the E4b declared-name refusal names the stage number.
  [existing rule `S/gate.py:126-137`; proposed stage number in the message]
- **CA-15 Agreement with an inverted keep form.** `escalate_if=sf.agreement() >= 0.8` (escalate on
  high agreement) → the keep form `agreement < 0.8` is refused by the E4b agreement rule; the message
  names the escalate form the author wrote. [existing `S/gate.py:152-161`]
- **CA-16 Wrong count of conditions.** `escalate_if=[c1]` for three stages (two gated) →
  `ValueError("sf.Cascade escalate_if= takes one condition or one per gated stage (2)")`. [proposed]
- **CA-17 Numeric quorum on a gated stage.** A gated stage with `quorum=N` → `ValueError("a cascade
  stage decides on the members that answered; it takes quorum='all'")`, because the stage panel
  is compiled with url4 `quorum=0` and the members that answered decide (ans:Q24); a numeric floor
  would be a second, conflicting rule. [proposed — gap §per-connection]
- **CA-18 Bad `otherwise`.** Anything but `None`, `"abstain"` or `"fail_closed"` → `ValueError`.
  [proposed]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| CA-19 | Every stage fails, last required | [stated ans:Q17] | H×M | Given all stages' members fail and `otherwise=None`, Then stages 1..n-1 escalate and the Case fails with the last stage's own failure code. |
| CA-20 | Every stage escalates, `otherwise="abstain"` | [stated epic] | H×M | Given every condition fails, Then all n stages ran once each and the Case abstains `gate_not_met` (the root JOIN copies the innermost abstain, branch-core BC-36); the report counts it declined. |
| CA-21 | Same bytes as hand-written Gates | [implied — ans:Q6] | H×M | Given the CA-1 Cascade and the equal hand-written Gate chain, Then both compile to byte-identical url4. |
| CA-22 | Rebuild shows the Gate form | [proposed] | M×M | Given the Cascade's url4, When `Url4.to_python()` runs, Then the code has nested `sf.Gate(...)` and no `sf.Cascade`; it recompiles to the same bytes (RB-1). |
| CA-23 | Default sample seeds collide | [proposed — gap §edge] | M×M | Given stage 2 uses `sf.samples(m, 5)` with default seeds after stage 1's `sf.samples(m, 2)`, Then the shortcut emits `CascadeSeedWarning` ("stage 2 repeats seeds 0, 1 of stage 1; give seeds= for fresh samples"), because equal requests can be gateway cache hits with the same text. |
| CA-24 | An optional member the author already marked | [proposed] | L×M | Given a member already `optional=True`, Then it stays optional and nothing else changes. |
| CA-25 | Nested Cascade in a branch | [stated ans:Q10] | M×L | Given a Cascade as `then=` of an input Gate, Then it compiles (depth counts toward the 8-Gate cap, branch-core BC-18). |
| CA-26 | Cascade as a Pipeline stage | [stated ans:Q10] | M×L | Given `cascade >> sf.Synthesize(w)`, Then the writer reads the Cascade's final answer; the Cascade stages still read `$input`. |
| CA-27 | Token-level escalation is refused by design | [stated epic non-goal] | L×L | The docs state that `sf.Cascade` decides per full answer; no API takes a token position. (Doc test only.) |
| CA-28 | `isinstance` | [proposed] | L×L | `sf.Cascade` is a function; the docstring says `isinstance(x, sf.Cascade)` is not supported (as `sf.Fusion`). |

## 4. Non-functional requirements

- No new Engine code: a Cascade runs only branch-core endpoints and E4b combine calls [implied].
- Cost: a Case that passes at stage 1 pays exactly stage 1's calls plus zero model calls for the
  rest (the branch-core guarantee) [stated epic].
- Observability: the report shows per Case the stage that answered and per run the share of Cases
  answered at each stage — CARGO's "fraction of calls that stay local" [stated epic; owned by
  [report](report.md)].
- Budget: a refused escalation keeps the current stage's answer, owned by [budget](budget.md)
  [stated ans:Q3].

## 5. Out of scope

- Per-token escalation inside one decode (STEER's inner loop) [stated epic].
- Parallel race that cancels slower branches (OME-1465 race form) [stated ans:Q5].
- Incremental sample top-up that reuses earlier samples (OME-1630) [stated ans:Q7].
- A stage that conditions on the previous stage's answer (that is today's Pipeline) [stated epic].
- Numeric quorum on a gated stage (CA-17) [proposed].

## 6. Open questions

None. The cross-PRD items (`sf.answered()` in erd §1 and [gate](gate.md); the null-branch
rule in [branch-core](branch-core.md) D4) are resolved there.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: outside-in on the shortcut (pure SDK, cheap) then the Engine-world runs, because CA-21
(same bytes as hand-written Gates) makes every run test a test of [gate](gate.md), which comes
first in the build. RED first, always.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `agreement_keep_form_refuses_less_than` (E4b P4: an agreement gate keeps the majority with `>=` / `>` only) | unit | [existing `S/gate.py:152-161`] | H×M | passes today |
| 2 | `stage_one_passes_and_later_stages_make_zero_calls` (Engine world, fake gateway counts calls per binding) | integration | CA-2 | H×H | shortcut + gate |
| 3 | `escalated_stage_reads_the_case_input_not_the_previous_answer` | integration | CA-3 | H×H | recipe body `$input` |
| 4 | `failed_gated_stage_escalates_instead_of_failing_the_case` | integration | CA-6 | H×H | members `optional=True`; stage panel url4 `quorum=0`; null branch → `otherwise` (D4) |
| 5 | `abstained_gated_stage_escalates` | integration | CA-7 | H×H | DECIDE missing-number rule |
| 6 | `partially_failed_stage_decides_on_the_members_that_answered` | integration | CA-29 | H×M | decision call reduces over the answered members |
| 7 | `cascade_equals_the_hand_written_nested_gates` | unit | CA-1 | H×H | `S/_surface/cascade.py` `Cascade` |
| 8 | `cascade_compiles_to_the_same_bytes_as_nested_gates` | unit | CA-21 | H×M | no own compile path |
| 9 | `escalate_form_maps_to_the_keep_form` (parametrized over the four cmps) | unit | CA-4 | H×M | `_keep(cond)` |
| 10 | `every_stage_escalates_and_the_case_abstains_gate_not_met` | integration | CA-9, CA-20 | H×M | innermost `otherwise` word; outer JOINs copy the `terminal` result (branch-core D12) |
| 11 | `every_stage_fails_and_the_last_failure_fails_the_case` | integration | CA-19 | H×M | last stage keeps required members |
| 11a | `gated_last_stage_with_no_voters_follows_the_otherwise_word` (`"abstain"` → abstain `no_votes`; `"fail_closed"` → Case failed `fail_closed`) | integration | CA-30 | H×M | branch-core D4 null rows |
| 12 | `first_success_returns_the_first_answer_verbatim` | integration | CA-10 | H×M | `sf.answered()`; auto-wrap |
| 13 | `adaptive_sampling_pays_two_or_two_plus_five` | integration | CA-11 | M×M | — |
| 14 | `one_condition_or_one_per_gated_stage` | unit | CA-5, CA-16 | M×M | arity check |
| 15 | `fewer_than_two_stages_is_refused` | unit | CA-12 | M×M | — |
| 16 | `gated_stage_without_a_reducer_is_refused` (parametrized: Model with condition, open Fanout, Synthesize end, narrow end) | unit | CA-13 | M×M | stage shape check |
| 17 | `undeclared_signal_names_the_stage` | unit | CA-14 | M×M | message adds stage number |
| 18 | `inverted_agreement_escalation_is_refused` | unit | CA-15 | M×L | E4b rule via keep form |
| 19 | `numeric_quorum_on_a_gated_stage_is_refused` | unit | CA-17 | M×L | — |
| 20 | `otherwise_takes_none_abstain_or_fail_closed` | unit | CA-18 | M×L | — |
| 21 | `to_python_writes_nested_gates_and_recompiles` | unit | CA-22 | M×M | rebuild via gate |
| 22 | `default_seed_collision_warns` | unit | CA-23 | M×M | `CascadeSeedWarning(EvaluationWarning)` |
| 23 | `author_optional_member_is_unchanged` | unit | CA-24 | L×M | — |
| 24 | `cascade_in_a_branch_counts_toward_the_depth_cap` | unit | CA-25 | M×L | — |
| 25 | `cascade_then_synthesize_reads_the_final_answer` | integration | CA-26 | M×L | — |
| 26 | `cascade_docstring_states_per_answer_and_no_isinstance` | unit | CA-27, CA-28 | L×L | doc test |

Pinned files: `ST/public_surface_snapshot.json` (new name `Cascade`, new warning
`CascadeSeedWarning`) — owner approval at the PR.

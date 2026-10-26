# PRD: Budget — a per-Case cap that every Gate branch checks

**Source:** epic OME-1291 behavior 3 ("A budget the decision can see"), ans:Q3, ans:Q13, ans:Q14,
ans:Q19 · **Priority:** P1 (PR-3) **Lifecycle:** existing records (E4a `budget.v1`, never written)
+ new enforcement · **Owner:** unassigned
Paths: [erd §1, §3, §5, §6](../erd.md) · contracts: C2, C6, C8 · components:
[branch-core](branch-core.md), [selectors](selectors.md) · display: [report](report.md)

## 1. Summary and user story

As a researcher whose result is a saving (OmniRouter, RouterBench willingness-to-pay, MTRouter,
VineLM, FutureWeaver), I want to write one spending cap on my candidate, and I want every optional
call inside it (a Gate branch, a cascade escalation, a fallback) to be refused before it is sent
when it would pass the cap, so that the cap is real money that the provider never bills, the
report shows spend against the cap and the refused call, and a replay takes the same decisions.

## 2. Background and constraints

- "A number, attached to the request, that decreases as calls happen. The selector and the
  cascade can read what is left. When the next call would pass the cap, it does not happen, and
  the current answer (or abstain, if there is none) is the result." [stated epic]
- "The author sets the cap in the recipe (USD once prices exist, otherwise a token cap,
  declared)." "Before each optional call, the runtime checks the cap. A call that would break it
  is not sent." "The report shows spend against the cap and which call was refused." "A cap that
  is only a comment in the prompt is not this." [stated epic]
- v1 units are USD and tokens; the "would exceed" check is spend so far plus an author-declared
  estimate. [stated ans:Q3]
- The cap covers one Case. [stated ans:Q13]
- A call with no known cost under a USD cap counts as $0, with a warning in the report.
  [stated ans:Q14 — the owner chose this against the recommendation; do not re-litigate]
- The cap is written once, on the candidate; every Gate branch inside checks it; conditions can
  read `sf.budget.remaining()`. [stated ans:Q19]
- No url4 grammar change. [stated ans:Q1]

### 2.1 Current behavior

- E4a defines the records and the charge rule and writes none of them:
  `Budget(unit, cap)` (`E/budget.py:53-62`); `BudgetCharge` with `source` `live` |
  `cache_reference` | `unpriced` (`:65-80`); `BudgetRefusal(reason="would_exceed_cap")`, "written by
  E4c" (`:83-95`); `BudgetState` with `start` and `apply` (`:118-182`). The module says "E4a
  declares no Budget on any request and writes no charge (BU-D4)" (`:5-6`). [existing]
- Charge rule `charge(signals, unit, cached=)` (`E/budget.py:185-197`): usd charges `cost_usd`,
  tokens charges `tokens_in + tokens_out`; a cache hit is charged its ORIGINAL cost as
  `cache_reference`; a missing or non-finite number makes the call `unpriced` (`:200-206`).
  [existing]
- The fold `_ledger` (`E/budget.py:98-115`): sums in `DECIMAL_CONTEXT`; an unpriced amount adds
  nothing to `spent` and one to the unpriced count; `remaining = max(cap - spent, 0)`. [existing]
  This is exactly the ans:Q14 rule.
- `BudgetStage = model | synthesis | judge | writer` (`E/budget.py:25`, SDK mirror
  `S/budget.py:25`). No `sample` and no `selector` stage. E4b part 7 D7 left the `sample` stage to
  E4c: "operation kind `sample` maps to budget stage `model`"
  (`docs/spec/2026-10-16-e4b-consistency/00-overview.md:156`). [existing]
- The SDK reserves `sf.signal("budget.remaining")` and refuses it: "budget.remaining is a
  request-level Budget value that E4c compares read; it is not an Answer signal"
  (`S/_signals.py:53-62`, raised at `:73-74`). [existing]
- report-trace.v1 reserves the trace kind `budget` with fields `event, operation_id, member_id,
  stage, amount, estimated, source, remaining_after` and no producer (`S/report_trace.py:17`,
  `:49-60`). [existing]
- url4 Spec B §4.1 defines typed budget annotations on a source (`article:0.9:tokens=4000:…`)
  and structured budgets with the reserved scopes `_each`, `_total`, `_mean` (§4.1.1.2, §4.1.1.6,
  "see §24.4"). The url4 package builds and renders them (`U/core/builders.py:140-180`
  `src(budgets=)`, `U/core/render.py:292-295`, `:606-612`) and enforces nothing (no budget reader
  in `U/dag/`). [existing]
- url4 Spec C: execution annotation `budget_mode` = `hard` (default, "budget exceedance fails the
  source", §24.1) | `advisory` ("logged and reported but does not fail the source", §24.3)
  (spec-C §10 table, line 104); an unsupporting node treats `advisory` as `hard` (line 125); error
  code `budget_exceeded`, permanent (line 1124). The url4 package classifies `budget_mode` as an
  execution key (`U/core/_annotations.py:194`). Spec Part E (§24, budgets) is not in the repo.
  [existing]
- USD per call comes from the gateway envelope through `usd_from_aigw` (`E/world/accounting.py:239`),
  `None` when the evidence cannot support a price. The run total latches unpriced on the first
  unpriced call (`E/runner/executor.py:492-509`). Per-Case recorded calls are readable by an
  endpoint through `current_operation_calls()`, as the combine step reads member accounting
  (`E/world/combine.py:82-96`). [existing]

Delta: the SDK writes the cap on the candidate; the Engine binds it per Case; DECIDE folds the
charges of the decision's ancestors, compares, refuses, and records; the SDK reads
`sf.budget.remaining()`; the report shows the result.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **BU-1 One cap on the candidate.** Given `sf.Budgeted(recipe, usd=0.05)`, When the candidate
  compiles, Then the url4 candidate source carries the typed budget annotation `usd=0.05` and the
  execution annotation `;budget_mode=advisory`, and no other source carries a budget.
  [stated ans:Q19; proposed annotation form]
- **BU-2 Both units.** Given `sf.Budgeted(recipe, usd=0.05, tokens=20000)`, Then the source carries
  both keys and every decision checks both; a branch is refused when either unit refuses.
  [stated ans:Q3; proposed "either refuses"]
- **BU-3 Optional call allowed.** Given a cap of $0.05, spend so far $0.01 and a branch estimate
  `sf.Estimate(big, usd=0.03)`, When the Gate wants that branch, Then the branch runs, and the
  decision record's budget view is `{unit: "usd", cap: 0.05, spent: 0.01, unpriced: 0,
  estimate: 0.03, refused: false}`. [stated epic; stated ans:Q3]
- **BU-4 Optional call refused, current answer kept.** Given spend $0.03, the wanted branch's
  estimate $0.03 (0.03 + 0.03 > 0.05), and the other branch a reducer step that makes no new call
  (a cascade's kept answer), Then the wanted branch is not sent, the other branch gives the answer,
  `branch ≠ wanted`, and `not_run` holds `{branch: <wanted>, reason: "budget_refused"}`. When that
  step's decision call abstained, the Gate abstains with the same reason; it never returns `""`
  marked `answered` ([branch-core](branch-core.md) D4, D12). [stated epic: "the current answer …
  is the result"; erd GD-I2]
- **BU-5 Refused with no current answer → abstain.** Given the wanted branch is refused and the
  other branch is also a body that makes a call (or the Gate is an input gate before any answer),
  Then neither branch runs, `branch` is null, both are in `not_run` (wanted: `budget_refused`, the
  other: `not_selected`), and the result is abstain with reason `budget_refused`; as the final node
  the Case is scored 0 with `abstained: true`. [stated epic: "or abstain, if there is none"; erd
  GD-I1, §6]
- **BU-6 The decision can see what is left.** Given an input gate
  `sf.Gate(when=sf.budget.remaining() >= 0.02, then=big, otherwise=small)` under a Budget, When
  DECIDE runs, Then `observed` is the remaining USD after the ancestors' charges, and the branch
  follows the comparison (OmniRouter: the chosen model is the one that fits). [stated epic;
  stated ans:Q19]
- **BU-7 Spend counts what already ran.** Given a cascade stage 1 (3 members) and a LabelModel
  selector before it, When the stage-2 decision runs, Then `spent` is the fold of the charges of
  the 4 calls in `GATE_SPEC.ancestors`, in that list order. The decision runs only after those
  calls resolved, because the Gate's AFTER source references their bindings
  ([branch-core](branch-core.md) D10). [stated epic: "decreases as calls happen"; proposed ancestor
  rule]
- **BU-8 Replay takes the same branch.** Given a captured run where every call is later served
  from the cache at $0 live cost, When the run replays, Then each charge is the call's reference
  cost (`cache_reference`), every budget view and every decision record is byte-identical, and the
  same branches run. [implied — erd GD-I6; existing charge rule `E/budget.py:185-197`]

### 3.2 Error paths

- **BU-9 Unknown cost counts $0 with a warning.** Given an ancestor call with `cost_usd = None`
  under a USD cap, Then it adds $0 to `spent` and 1 to `unpriced`, the decision proceeds, and the
  report shows a budget warning for the Case ("N calls with unknown cost counted as $0").
  The same holds for a tokens cap when `tokens_in` or `tokens_out` is unknown.
  [stated ans:Q14; existing `E/budget.py:98-115`]
- **BU-10 Mandatory calls are never refused.** Given a cap of $0.01 and a stage-1 panel that
  spends $0.04, Then stage 1 runs in full (the check is "before each optional call" only), the
  first decision sees `spent = 0.04 > cap`, refuses any wanted branch that makes a call, and the
  budget view shows the over-cap spend; the Case does not fail. [stated epic; proposed —
  `budget_mode=advisory`]
- **BU-11 Budget not at the root.** Given `sf.Budgeted(...)` used as a Pipeline stage, a branch
  body, a Fanout member or a nested Budget, When the SDK builds it, Then it raises "sf.Budgeted
  wraps the whole candidate: use it once, at the root". [stated ans:Q19]
- **BU-12 `sf.budget.remaining()` with no Budget.** Given a Gate that reads
  `sf.budget.remaining()` in a candidate with no `sf.Budgeted`, When the candidate compiles, Then it
  raises "sf.budget.remaining() needs sf.Budgeted(...) on the candidate". [proposed]
- **BU-13 Ambiguous unit.** Given `sf.Budgeted(recipe, usd=…, tokens=…)` and a Gate reading
  `sf.budget.remaining()` with no unit, Then it raises "name the unit: sf.budget.remaining('usd')
  or ('tokens')"; with one declared unit the argument is optional. [proposed]
- **BU-14 Invalid caps and estimates.** Given a cap ≤ 0, NaN, infinite, a non-integer tokens cap,
  no unit at all, or an estimate < 0 / non-finite / non-integer for tokens, Then the SDK refuses
  with the E4a cap messages (`E/budget.py:42-46`); an estimate in a unit the Budget does not
  declare is refused ("sf.Estimate names usd, but sf.Budgeted declares only tokens"). [existing cap
  rules; proposed estimate rules]
- **BU-15 Engine refuses a stray annotation.** Given a hand-written url4 with a typed budget on a
  non-candidate source, or a candidate budget key other than `usd`/`tokens`, When the Case starts,
  Then the Engine raises the permanent `benchmark_definition_error` naming the key, before any call.
  [proposed — gap §security]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| BU-16 | No estimate = refuse only when exhausted | [stated ans:Q3; proposed rule] | H×M | Given a wanted recipe branch with no `sf.Estimate`, Then it is refused iff `spent >= cap` (remaining 0), never on a guess. |
| BU-17 | Exact boundary | [proposed — gap §boundary] | H×M | Given `spent + estimate == cap` exactly (Decimal fold), Then the branch is allowed (refuse only on `>`); `spent == cap` with no estimate is refused. |
| BU-18 | Steps that call are optional calls too | [implied — epic "each optional call"] | H×M | Given an E4b panel gate whose fallback is `sf.JudgePick(j)`, Then the fallback branch is checked like a recipe branch; `sf.Estimate(sf.JudgePick(j), usd=…)` gives its estimate; the majority branch (a Vote, no call) is the current answer when it is refused. |
| BU-19 | Ancestors only; parallel overspend accepted | [stated ans:Q20] | H×M | Given two sibling Gates (or three selected skip-Gate members) in one Case, Then each decision counts only its own ancestors; a call that runs in parallel and is not an ancestor never enters `spent`, so siblings can jointly pass the cap. The report shows the run's spend over the cap as an `overspend` line ([report](report.md)). |
| BU-20 | An ancestor with no record | [proposed — gap §per-hop failure] | M×M | Given an optional ancestor that failed before sending (no recorded call), Then it charges nothing and is not counted as unpriced; a recorded call that failed after sending charges what its accounting says. |
| BU-21 | Selector and sample calls count | [stated ans:Q8; existing `docs/spec/2026-10-16-e4b-consistency/00-overview.md:156`] | M×M | Given a LabelModel selector and an `sf.Consistency` member, Then their calls are charged with stage `selector` and `model` (D7: kind `sample` → `model`). |
| BU-22 | Nested Gates see a growing spend | [implied] | M×M | Given a cascade of 3 stages, Then the stage-3 decision's `spent` includes stage 1 and stage 2, and its `remaining` is never larger than stage 2's. |
| BU-23 | `sf.budget.remaining()` is never an Answer signal | [existing `S/_signals.py:53-62`] | M×L | Given `sf.signal("budget.remaining")`, Then the SDK keeps its E4a refusal; only `sf.budget.remaining()` is accepted, and only in an input gate's `when`. |
| BU-24 | Estimate on a body that makes no call | [proposed] | L×M | Given `sf.Estimate(sf.Vote(), usd=…)` or on a word, Then the SDK refuses it ("sf.Estimate wraps a branch that makes model calls"), erd GS-I3. |
| BU-25 | Trace rows | [proposed] | L×M | Given a refused branch, Then the trace has one `budget` row `{event: "refusal", operation_id: <first operation of the refused body>, stage, amount: null, estimated, source: null, remaining_after}`; the reserved kind gets its first producer; charges stay in `model_call` rows. |
| BU-26 | Large ancestor list | [proposed — gap §capacity] | L×L | Given 256 ancestors (Fanout cap), Then the fold stays one pass over the recorded calls (index by fingerprint, no N×M scan). |
| BU-27 | Replay flags a differing budget view | [stated ans:Q21] | M×M | Given a pinned-cache reproduction where a call that was priced live comes back unpriced, When DECIDE recomputes the budget (Q14: $0), Then the SDK compares each replayed decision's BUDGET_VIEW with the captured run's record of the same `gate_id` (when the captured report holds it) and marks the Case `budget_view_differs`; the report shows the flag ([report](report.md)). No captured view is reused. |
| BU-28 | One cap per Attempt | [proposed — P21] | M×L | Given a Benchmark that asks each Case several times (Attempts), Then each Attempt starts with the full cap; one Attempt's spend never reduces another's. |

## 4. Non-functional requirements

- Decimal fold in `DECIMAL_CONTEXT`, never float sums (`E/budget.py:98-115`) [existing].
- One pass: DECIDE indexes `current_operation_calls()` by fingerprint (path, params) once;
  O(ancestors). Under `sf.Budgeted` every call carries the `binding` param, so each ancestor
  fingerprint has one claimant ([branch-core](branch-core.md) D3, D7) [proposed].
- Determinism: the budget view is a pure function of the ancestor list and the recorded accounting
  with reference costs; no clock, no run-level state (per Case only, ans:Q13) [implied].
- Observability: the decision log line adds `budget=<refused|ok> spent=<n> cap=<n>` per unit; an
  unpriced count > 0 logs once per Case [proposed].
- Security: the cap and estimates are numbers checked at compile and again at the Engine; a
  hand-written url4 cannot carry a budget on an inner source (BU-15) [proposed].

## 5. Out of scope

- A run-level cap across Cases [stated ans:Q13].
- Refusing a call when its cost is unknown (the recommended option the owner did not take)
  [stated ans:Q14].
- A price table or a `max_tokens × price` estimator; estimates are author-declared [stated ans:Q3].
- The url4 scoped budgets `_each` / `_total` / `_mean` and domain-conditional budgets (Spec B
  §4.1.1.2): E4c writes one scalar per unit [proposed].
- Multi-provider accounts and local hardware (OME-1356 except spend-vs-cap) [stated ans:Q5].

## 6. Open questions

Questions for the url4 spec owner (not product questions; they do not block v1):
1. Spec Part E §24 is not in the repo. E4c writes `;budget_mode=advisory` on the candidate source
   because mandatory calls may pass the cap and must not fail the Case (BU-10). Confirm that an
   advisory candidate budget plus "the node never sends an optional call that would exceed" is
   conformant with §24.1/§24.3. Fallback if not: write no `budget_mode` and keep the cap only in
   E4c's own check.
2. Confirm that `usd` is an acceptable typed budget key (the Spec B examples show `tokens` and
   `influence`; the key namespace is open, §4.1.1.3).

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: core-out — the pure fold and refusal rule first, then the url4 carriage, then the
Engine-world runs, because a wrong fold silently overspends. RED first, always. CHAR rows pin the
E4a records this PRD starts to write. PIN rows are owner-approved edits of pinned files.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `budget_charge_rule_reference_cost_on_cache_hit` (E4a `charge` with `cached=True` → `cache_reference`) | unit | [existing `E/budget.py:185-197`] | H×M | passes today |
| 2 | CHAR `budget_ledger_counts_unpriced_as_zero` | unit | [existing `E/budget.py:98-115`] | H×M | passes today |
| 3 | CHAR+keep `signal_budget_remaining_still_refused` | unit | BU-23 | M×L | passes today; must stay green |
| 4 | `refuse_when_spent_plus_estimate_exceeds_cap` (decision table: estimate given/absent × below/equal/above, per unit) | unit | BU-3, BU-4, BU-16, BU-17 | H×H | `E/world/branch.py` `_budget_view` + refusal rule |
| 5 | `refused_branch_falls_back_to_the_no_call_branch` (incl. a fallback to an abstained `then` step slot → the Gate abstains with that reason, never `""` answered; moved from branch-core #9) | unit | BU-4, GD-I2 | H×H | DECIDE branch selection; JOIN copies the decision call's result (branch-core D4, D12) |
| 6 | `refused_with_no_current_answer_abstains_budget_refused` | integration | BU-5 | H×H | JOIN abstain; `AbstainReason` + `budget_refused` (both sides) |
| 7 | `spent_folds_only_listed_ancestors_in_order` | unit | BU-7, BU-19 | H×H | index recorded calls by fingerprint |
| 8 | `either_unit_refuses` | unit | BU-2 | H×M | per-unit loop |
| 9 | `replay_from_cache_gives_identical_budget_views` | integration | BU-8 | H×M | charge with `cached` from the recorded cache outcome |
| 10 | `unknown_cost_counts_zero_and_warns` (usd and tokens) | integration | BU-9 | H×M | `unpriced` → report warning |
| 11 | `mandatory_stage_over_cap_runs_and_is_reported` | integration | BU-10 | H×M | no check outside DECIDE |
| 12 | `budget_compiles_to_candidate_source_annotation` (rendered url4 bytes: `usd=0.05`, `;budget_mode=advisory`) | unit | BU-1 | H×M | SDK root wrapper → `src(budgets=…)` |
| 13 | `engine_binds_candidate_budget_once_per_case` | integration | BU-1 | H×M | read the annotation at candidate invocation start (`E/benchmarks/invocation.py:35`) into a ContextVar set before the expression runs, so every task inherits it (branch-core D11) |
| 14 | `budget_remaining_is_observed_in_an_input_gate` | integration | BU-6 | H×M | `observe: "budget.remaining:<unit>"` in GATE_SPEC |
| 15 | `step_fallback_is_checked_as_an_optional_call` (E4b JudgePick fallback refused → majority answer) | integration | BU-18 | H×M | lazy-fallback body is a checked branch |
| 16 | `parallel_skip_members_can_jointly_pass_the_cap_and_report_overspend` | integration | BU-19 | H×M | per-DECIDE ancestors only (ans:Q20) |
| 17 | `engine_refuses_budget_on_inner_source_or_unknown_key` | integration | BU-15 | M×M | parse check before any call |
| 18 | `budget_not_at_root_is_refused` (stage, branch, member, nested) | unit | BU-11 | M×M | SDK compile check |
| 19 | `budget_remaining_without_budget_is_refused` | unit | BU-12 | M×M | compile check |
| 20 | `invalid_caps_and_estimates_are_refused` (parametrized) | unit | BU-14, BU-24 | M×M | E4a `_check_cap`; estimate checks |
| 21 | `ancestor_without_record_charges_nothing` | unit | BU-20 | M×M | missing record ≠ unpriced |
| 22 | PIN `budget_stage_gains_selector` (`BudgetStage` both sides + `budget_schemas()` freeze snapshot) and `sample_maps_to_model` | unit | BU-21 | M×M | owner-approved schema snapshot edit |
| 23 | `nested_decisions_see_growing_spend` | integration | BU-22 | M×M | ancestors grow with depth |
| 24 | `replay_marks_a_differing_budget_view` | unit | BU-27 | M×M | SDK reproduction compares BUDGET_VIEW per `gate_id` |
| 25 | `each_attempt_starts_with_the_full_cap` | integration | BU-28 | M×L | bind the cap per Attempt scope |
| 26 | `budget_remaining_needs_a_unit_with_two_units` | unit | BU-13 | L×M | — |
| 27 | `refusal_writes_one_budget_trace_row` | unit | BU-25 | L×M | first producer of TraceKind `budget` |
| 28 | `fold_is_one_pass_over_256_ancestors` (operation count bound, not wall time) | unit | BU-26 | L×L | dict index |

Pinned files this PRD expects to touch (owner approval at build time): the Engine budget schema
freeze snapshot (`budget_schemas()` output) and the SDK `S/budget.py` stage list test; the SDK
answer schema `ST/data/schemas/screamingface.answer.v1.json` and the combine-evidence v1 schema
snapshot for the abstain reason `budget_refused`; `ST/public_surface_snapshot.json` for
`sf.Budgeted`, `sf.Estimate`, `sf.budget`.

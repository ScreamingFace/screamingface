# PRD: Report — show what ran, what was skipped and why

**Source:** epic OME-1291 ("the report says it was not selected and why"; "The report shows the
selector input summary, the label, and which branches made zero calls"; "The report shows every
stage that ran, the signal value, the comparison, and the stages that did not run"; "The report
shows spend against the cap and which call was refused"; "If a guard fires, the report says which
guard, and the selector's original label is still recorded"), ans:Q14, ans:Q16, ans:Q18
· **Priority:** P0 (the skip is invisible without it; CARGO's claim "is invisible if both always
run" [stated epic])
**Lifecycle:** existing (characterize + delta) — extends the E4b part 4 report surfaces
**Owner:** unassigned
Paths: [erd §2, §3, §5, §6](../erd.md) · contracts: C5, C8 · components:
[branch-core](branch-core.md), [selectors](selectors.md) · data from: [gate](gate.md),
[cascade](cascade.md), [skip-members](skip-members.md), [guards](guards.md), [budget](budget.md)

## 1. Summary and user story

As a researcher whose result is a saving (a small model answers the easy questions, one
specialist answers instead of a panel), I want the report to show, per Case, every Gate decision:
the condition, the number or label it read, the branch that ran, the branches that made zero calls
and why, the budget spent against the cap, and which guard ended the Case; and, per run, how often
each branch ran and how many model calls the skips avoided, so that I can prove the saving and
audit every skip from the report alone.

## 2. Background and constraints

- "This epic adds three constructs. They share one rule: a branch that is not selected makes zero
  model calls, and the report says it was not selected and why." [stated epic]
- "The report shows the selector input summary, the label, and which branches made zero calls."
  [stated epic]
- "The report shows every stage that ran, the signal value, the comparison, and the stages that
  did not run." [stated epic]
- "The report shows spend against the cap and which call was refused." [stated epic]
- "If a guard fires, the report says which guard, and the selector's original label is still
  recorded." [stated epic] With a model selector, a fired guard means no model call: the label
  shows "not run". [stated ans:Q18]
- "The point of the paper [CARGO] is the fraction of calls that stay local. That fraction is
  invisible if both always run." [stated epic]
- "Abstain is a scored decline. Fail-closed is an error. They must not share a status code."
  [stated epic] The report counts them apart. [implied]
- A call with unknown cost counts as $0 under a USD cap, with a warning in the report.
  [stated ans:Q14]
- An unselected skip-Gate member shows `not_selected`. [stated ans:Q16]
- The data source is the `gate-decision.v1` record on the JOIN operation
  ([erd §3](../erd.md), [branch-core](branch-core.md) BC-7). The report computes nothing the record
  does not hold, except counts and the topology-derived "not reached". [implied]

### 2.1 Current behavior

- `CaseOperation` holds `operation_id`, `output`, `finish_reason`, `accounting`, `combine`
  (`S/case_result.py:292-338`); `to_dict` writes `combine` only when set ("absence stays absence",
  `:333-336`) [existing].
- The strict decoder reads `combine` with `decode_combine_evidence`
  (`S/_evaluation/results.py:480`; `S/_evaluation/combine_evidence.py:93-120`): an unknown key, a
  missing key or a wrong schema id raises `ExecutionError` ("an Engine/SDK version mismatch …
  fails loudly instead of dropping evidence") [existing].
- The Case pane writes one Combine section per combine step, in operation order
  (`S/_ui/combine_view.py:99-124` `combine_sections_html`), called from the Case detail
  (`S/_ui/report_view.py:959`) [existing]. A step with no evidence gets a short section
  (`_no_evidence_section`, `:152`; E4b part 4 P19) [existing].
- Numbers show at 4 significant digits with the exact stored value as the hover title; a missing
  value is an em dash whose title is the reason (`number_html` `:65-72`, `dash_html` `:75-77`)
  [existing]. Text cells are escaped and cut at 80 characters (`text_html` `:80-84`) [existing].
- The E4b gate shows a chip; a gate that did not run reads `_GATE_NOT_RUN` = "the vote found no
  answer, so the gate did not run" (`:38`, `_gate_chip` `:318-324`) [existing].
- The run summary is fed one Case at a time in ONE pass that also counts abstained Cases
  (`S/_ui/report_view.py:359-363`; `CombineSummary` `S/_ui/combine_view.py:472-509`; E4b E7: "a
  saved Candidate decodes a Case on each read (DiskCases), so the card reads the Cases once")
  [existing]. `_StepSummary` already counts gate branches `majority`, `fallback`, `band`,
  `not_run` (`:536-539`, `_add_gate` `:579-590`) [existing].
- The report.v1 export writes `case.to_dict()` then `trace` only for Cases with combine evidence
  (`S/report.py` `_export_cases`, "the key appears only with combine evidence, so every other Case
  exports byte-identically") [existing].
- `TraceKind` is closed at `model_call | extract | reduce | budget`; a new kind needs
  `report-trace.v2` or an owner-approved v1 edit (`S/report_trace.py:1-6`, `:18`) [existing].
- Attempt operations are not shown or exported (E4b part 4 P15) [existing].
- The workflow view maps `not_run` to "Skipped" at workflow level only
  (`S/_ui/evaluation_view.py:250`) [existing]. No view shows a branch that did not run, a selector
  label, a budget line or a `fail_closed` count [existing].

Delta (this PRD):

1. `CaseOperation.decision: GateDecision | None`, decoded strictly; `to_dict` writes it only when
   set. So the report.v1 export carries `operations[].decision` additively, with no new trace kind
   and no `report-trace.v2`.
2. A Case pane "Branches" section per Gate, in nesting order.
3. A `GateSummary` fed in the same one pass as `CombineSummary`, shown on the Candidate card.
4. Card counts `declined` (abstain) and `fail_closed` apart.

## 3. Scenarios and acceptance criteria (Given/When/Then)

### 3.1 Happy path

- **RP-1 Decode.** Given an Engine Case whose JOIN operation has a `decision`, When the SDK decodes
  the report, Then `case.operations[i].decision` is a frozen `GateDecision` with every erd §3 field,
  and `to_dict()` writes the same JSON back byte for byte. [proposed — mirrors
  `decode_combine_evidence`]
- **RP-2 Export.** Given a report with Gate decisions, When `report.to_json()` runs, Then each
  JOIN operation of each Case holds `decision`; an operation without a decision has no
  `decision` key; a report with no Gate exports byte-identically to today. [proposed; existing
  rule `S/case_result.py:333-336`]
- **RP-3 One section per Gate.** Given a Case with an outer guard Gate whose `otherwise` is an
  N-way chain of two nested label Gates, When the Case pane renders, Then it shows a "Branches"
  block with one section per Gate that ran, outer first, each nested section indented one level
  under the branch that contains it. [stated epic; stated ans:Q12]
- **RP-4 Condition in source form.** Given a section, Then its heading names the Gate
  (`gate · <label>`, the topology label) and its first line is the condition in the source form
  the author wrote: `sf.label(sel_1) == 'math'`, `sf.labels(sel_2).has('code')`,
  `sf.agreement() >= 0.8`, `sf.signal('conf').chosen() < 0.7`, `sf.budget.remaining() >= 0.02`.
  [stated epic: "the comparison"]
- **RP-5 Observed value.** Given a numeric condition, Then the observed value shows with
  `number_html` (4 significant digits, exact on hover) and the result `passed` / `failed`; a
  missing number is an em dash with the title "no number to compare". Given a label condition,
  Then the observed label(s) show as escaped text. [stated epic: "the signal value"; existing
  `S/_ui/combine_view.py:65-77`]
- **RP-6 Branch taken and branches not run.** Given a decision, Then the section shows
  `ran · then` (or `otherwise`) and, for each NOT_RUN_ENTRY, `not run · <branch> ·
  <reason> · avoided <min>–<max> model calls` (one number when min = max), reason text `not
  selected` or `refused by the budget`. [stated epic: "which branches made zero calls"; stated
  ans:Q22]
- **RP-7 Selector input summary.** Given a condition that reads a selector, Then the section shows
  one line per SELECTOR_RECORD: kind (`keywords` / `label model`), id, the input summary
  (`input · <N> characters` and, for Keywords, the window note when N > 65,536), and the labels:
  `label · math`, `labels · math, code`, `no match`, `unrecognized · "<raw>"`, `unparsed`,
  `failed · the default branch ran` (status `failed`; title: "the selector call failed; its code is
  in the activity view"), or `not run` (Q18). It never re-renders the Case input text (the Case
  pane already shows it). [stated epic: "the selector input summary, the label"; stated ans:Q18;
  proposed failed line — review 2 F10]
- **RP-8 Guard.** Given a Gate whose taken branch is the word `fail_closed`, Then its section shows
  `guard fired · fail_closed`, and every model selector below it that did not run shows
  `not run`; the Case header shows the failure code `fail_closed`, never "abstained".
  [stated epic; stated ans:Q18]
- **RP-9 Abstain.** Given a Gate whose result is `abstain`, Then the section shows
  `result · abstained · <reason>` (`gate_not_met` or `budget_refused`). [stated epic]
- **RP-10 Budget lines.** Given a decision with `budget`, Then the section shows one line per unit:
  `budget · usd · spent 0.01234 of 0.05` (both with `number_html`), `estimate 0.02` when set, and
  `refused` when `refused` is true, naming the refused branch. [stated epic: "spend against the
  cap and which call was refused"]
- **RP-11 Unpriced warning.** Given a budget entry with `unpriced > 0`, Then the section shows the
  warning `<n> calls with unknown cost counted as $0` (title: "the provider gave no cost; the
  budget counts these calls as $0"). [stated ans:Q14]
- **RP-12 Not reached.** Given an outer Gate whose `otherwise` body (containing two nested Gates)
  did not run, Then under the not-run line the pane lists the nested Gates as
  `gate · <label> · not reached` from the Candidate topology (no record exists for them,
  [branch-core](branch-core.md) BC-6, BC-16). [implied]
- **RP-13 Skip-Gate members.** Given a Fanout with skip-Gate members, Then the Gate sections show
  `not run · then · not selected` for each unselected member, and the block's Combine section
  shows those members with status `not_selected` and the note `not selected by sel_<n>`, so a
  skipped member reads differently from a member that a narrow step cut ([skip-members](skip-members.md),
  evidence key `skipped`). [stated ans:Q16; proposed note — reconciled with skip-members]
- **RP-14 Panel gate link.** Given a panel Gate, Then its section shows `decided by · combine ·
  <label>` linking to the decision call's Combine section, and the E4b gate chip there stays
  unchanged. [implied — erd §3 `panel`]
- **RP-15 Run summary per Gate.** Given a Candidate, When the card renders, Then a "gates" block
  shows, per Gate id that ran on at least one Case: Cases decided, `then` count, `otherwise`
  count, `none` count (both branches refused), bodies not run, model calls avoided as a range
  (sum of `model_calls.min` – sum of `model_calls.max`), budget refusals, `fail_closed` results,
  abstain results, unrecognized and unparsed selector counts, Cases with unpriced warnings, Cases
  whose final spend passed the cap (`overspend`, ans:Q20) and, in a reproduction, Cases marked
  `budget_view_differs` (ans:Q21). [stated epic; stated ans:Q20; stated ans:Q21; stated ans:Q22]
- **RP-16 Ladder (CARGO fraction).** Given a chain of Gates where each Gate after the first is the
  `otherwise` body of the one before (a Cascade or an N-way router), When the summary renders,
  Then it shows one ladder line per chain: for each Gate in order, the share of the chain's Cases
  that ended in that Gate's `then`, and the share that reached the last `otherwise`; the first
  share is labelled `resolved at the first branch` (CARGO: "the fraction of calls that stay
  local"). Shares show as percent with one decimal and the counts in the hover title.
  [stated epic]
- **RP-17 Card counts.** Given a Candidate, Then the card's context line shows `declined <n>`
  (abstained Cases, existing count) and, when non-zero, `fail_closed <m>` (Cases whose failure
  code is `fail_closed`), as two different counts. [stated epic]

### 3.2 Error paths

- **RP-18 Failed Case with no operations.** Given a Case failed with code `fail_closed` whose
  `operations` is None (or holds no decision), When the pane renders, Then it shows a short
  Branches line `a guard ended the Case · fail_closed · no decision record`; the run summary
  counts the Case in `fail_closed` from the failure code, not from a record. [proposed —
  gap §per-flow/failure]
- **RP-19 Gate with no record.** Given a Case operation whose topology node is a Gate JOIN but
  whose `decision` is None (the Case failed in a body, [branch-core](branch-core.md) BC-10, or the
  Engine attributed nothing), Then the pane shows `gate · <label> · decision · —` with the title
  "no decision record for this gate", and the summary does not count it. [proposed — E4b P19
  precedent]
  Given a record with `result: null` (DECIDE's record after a failed body, branch-core D3), Then
  the section renders the decision and `result · —` with the title "the branch did not finish".
  [proposed]
- **RP-20 Malformed record.** Given a `decision` with an unknown key, a missing key, a wrong schema
  id or a broken invariant (GD-I1, GD-I2, GD-I4, SR-I1 – SR-I3), When the SDK decodes it, Then it
  raises `ExecutionError` naming the field path (`Case Operation decision not_run[0] reason`)
  and never echoes values, the same policy as `combine`. [existing policy
  `S/_evaluation/combine_evidence.py:93-100`]
- **RP-21 Old reports.** Given a saved report.v1 file written before E4c, When it is reopened
  (`sf.reports.get`), Then it decodes and renders unchanged: no Branches block, no gates summary.
  [implied]
- **RP-22 Older SDK, newer Engine.** Given an SDK without this PRD and an Engine that writes
  `decision`, When the SDK decodes the Case, Then the strict decoder refuses the unknown key with
  its version-mismatch error. So the SDK side ships first (OME-1233 order). [existing policy;
  implied]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| RP-23 | Escaping of labels and raw tokens | [proposed — gap §security] | H×M | Given a LabelModel reply token `<img onerror=x>` recorded as `raw`, When the pane renders, Then the token shows escaped inside quotes, cut at 64 characters, and no tag reaches the HTML. |
| RP-24 | Summary in one pass | [existing `S/_ui/report_view.py:359-363`] | H×M | Given 10,000 saved Cases, When the card renders, Then `GateSummary.add` runs in the same loop as `CombineSummary.add` and the Cases are decoded once (a DiskCases read counter equals the Case count). |
| RP-25 | Counts add up | [implied] | H×M | Given any Candidate, Then for each Gate `then + otherwise + none == decided`, and the `model calls avoided` range equals the sums of `model_calls.min` and `model_calls.max` over the not-run entries. |
| RP-34 | Overspend line | [stated ans:Q20] | H×M | Given a Case whose recorded calls under `sf.Budget` charge more than the cap (parallel optional siblings, or mandatory calls), Then its Branches block shows `budget · overspend · spent <x> of <cap>` and the summary counts it in `overspend`. |
| RP-35 | Replay budget-view flag | [stated ans:Q21] | M×M | Given a reproduction Case marked `budget_view_differs` ([budget](budget.md) BU-27), Then the Branches block shows `budget view differs from the captured run` on that decision and the summary counts it. |
| RP-26 | Lone Gate | [proposed] | M×M | Given a lone Gate (not in an `otherwise` chain), Then it gets no ladder line, only its row. |
| RP-27 | Nested chain inside a `then` | [proposed] | M×M | Given a Cascade inside the `then` body of a guard, Then the ladder's denominator is the Cases where the Cascade's first Gate ran, not all Cases. |
| RP-28 | Budget on every Gate of the chain | [implied] | M×M | Given a Budget and a three-Gate chain, Then each section shows its own `spent` (it grows down the chain) and the summary counts refusals per Gate. |
| RP-29 | Attempt operations | [existing `docs/spec/2026-10-15-e4b-show-signals/00-overview.md:114` P15] | L×L | Given a Benchmark with Attempts, Then Gates of `case.attempts[i]` are not shown and not counted (same rule as Combine). |
| RP-30 | Long labels and many labels | [proposed — gap §boundary] | M×L | Given a multi selector with 32 labels, Then the labels line shows the first 8 and `+24 more` with the full list in the title. |
| RP-31 | Deep nesting display | [proposed — gap §boundary] | L×L | Given 8 nested Gates, Then the indentation stops growing after level 4 and each section names its depth (`level 6`). |
| RP-32 | Accessibility | [proposed] | M×L | Given the Branches block, Then status words (`ran`, `not run`, `refused`, `fail_closed`) are text, never colour alone; every em dash and abbreviation has a title. |
| RP-33 | Panel gate whose decision call has no evidence | [implied] | L×M | Given a panel Gate whose combine call has no evidence (P19), Then the Gate section still renders from its own record and the link reads `decided by · combine · <label> · no evidence`. |

## 4. Non-functional requirements

- Performance: the pane builds the topology index once per Case pane (as `accounting_index`,
  `S/_ui/combine_view.py:111`); `GateSummary.add` is O(decisions in the Case); the card makes one
  pass over the Cases (RP-24). Target: ≤ 50 ms added to the card for 10,000 Cases with 3 Gates
  each on the test host [proposed].
- Escaping: every label, raw token and source-form text goes through `html.escape`; raw tokens are
  cut at 64 characters before escaping (erd SELECTOR_RECORD `raw`) [proposed].
- Observability: a decode failure names the field path (RP-20); a Gate operation with no record is
  visible (RP-19), so "no Gate" and "a Gate with no record" never look the same [proposed].
- Determinism: the pane and the summary read only the record and the topology; the same report
  renders the same HTML live and after a reload [implied].
- No new trace kind; `TraceKind` stays closed (`S/report_trace.py:18`). The reserved, existing kind
  `budget` gets its first producer: one `event: "refusal"` row per refused branch
  ([budget](budget.md)); the trace view lists it like the other rows [proposed — reconciled with
  budget].

## 5. Out of scope

- A Python accessor such as `case.decisions()` (E4b part 4 had none either; the record is on
  `case.operations[i].decision`) [proposed].
- Charts of branch shares over time, leaderboard columns for routed recipes [proposed].
- Showing Gates of Attempt operations (E4b P15 rule) [existing].
- Clusters selector display (centroid and concept scores; Routesplain) [stated ans:Q4].
- A price table or a dollar estimate of the calls avoided; v1 counts model calls only
  [stated ans:Q3 — no price table].

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: outside-in from the wire. Decode and export first (a decode bug loses every later view),
then the Case pane, then the summary. RED first, always; a test that passes at once proves
nothing. CHAR rows pin today's report bytes and the Combine views. Fixtures: hand-built Cases with
records from `ET/data/gate_contract/decision_cases.json` (the Engine contract fixture of
[branch-core](branch-core.md)), never a live run.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `report_without_gates_exports_byte_identically` (goldens `ST/data/report_v1_combine_report.json`, `report_v1_vote_median_report.json` unchanged) | unit | RP-2 | H×H | passes today |
| 2 | CHAR `combine_sections_and_summary_are_unchanged_without_gates` | unit | §2.1 | H×M | passes today |
| 3 | `decision_decodes_and_round_trips_byte_for_byte` | unit | RP-1 | H×H | `S/_evaluation/gate_decision.py` `decode_gate_decision`; `CaseOperation.decision`; `GateDecision.to_dict` |
| 4 | `decision_decoder_refuses_unknown_missing_and_wrong_schema_without_echo` (parametrized, incl. invariants GD-I1/I2/I4, SR-I1–I3) | unit | RP-20 | H×H | closed key sets, field-path messages |
| 5 | `export_writes_decision_only_on_join_operations` (new golden `ST/data/report_v1_gate_report.json`) | unit | RP-2 | H×H | `CaseOperation.to_dict` |
| 6 | `fail_closed_case_counts_apart_from_abstained` | unit | RP-17, RP-8 | H×H | card context line; count from failure code |
| 7 | `not_run_lines_show_reason_and_model_calls_range` | unit | RP-6 | H×H | NOT_RUN_ENTRY render |
| 8 | `old_saved_report_reopens_without_branches_block` | unit | RP-21 | H×M | — |
| 9 | `fail_closed_case_without_operations_shows_short_line` | unit | RP-18 | H×M | pane fallback |
| 10 | `branches_section_per_gate_in_nesting_order_with_indent` | unit | RP-3 | H×M | `S/_ui/branch_view.py` `branch_sections_html` |
| 11 | `condition_renders_in_source_form` (parametrized: label eq, label ne, labels has, labels empty, agreement, chosen, mean, answered) | unit | RP-4 | H×M | one renderer shared with `repr` of [gate](gate.md) |
| 11a | `budget_remaining_condition_renders_in_source_form` | unit | RP-4 | M×M | same renderer; built with the budget (PR-3) |
| 12 | `selector_lines_show_labels_and_parse_states` (no match, unrecognized, unparsed, not run) | unit | RP-7 | H×M | SELECTOR_RECORD render |
| 13 | `fired_guard_shows_guard_and_model_selector_not_run` | unit | RP-8 | H×M | — |
| 14 | `raw_token_is_escaped_and_cut_at_64` | unit | RP-23 | H×M | `escape(short(raw, 64))` |
| 15 | `budget_lines_show_spent_cap_estimate_and_refusal` | unit | RP-10 | H×M | BUDGET_VIEW render |
| 16 | `gate_summary_counts_add_up` (property over generated records) | unit | RP-15, RP-25 | H×M | `GateSummary`, `_GateRow` |
| 17 | `ladder_shows_share_resolved_at_each_branch` | unit | RP-16 | H×M | chain detection from topology `otherwise` slots |
| 18 | `card_feeds_gate_summary_in_the_single_case_pass` (DiskCases read counter) | unit | RP-24 | H×M | extend the E7 loop `S/_ui/report_view.py:359-363` |
| 19 | `overspend_line_and_count` | unit | RP-34 | H×M | sum of charges vs cap per Case |
| 20 | `observed_number_uses_4_significant_digits_and_exact_title` | unit | RP-5 | M×M | reuse `number_html` |
| 21 | `unpriced_calls_show_counted_as_zero_warning` | unit | RP-11 | M×M | — |
| 22 | `nested_gates_of_not_run_body_show_not_reached` | unit | RP-12 | M×M | topology walk over kind `gate` children |
| 23 | `gate_operation_without_record_shows_dash_section` | unit | RP-19 | M×M | `_no_decision_section` |
| 24 | `skip_gate_members_show_not_selected_in_both_sections` | unit | RP-13 | M×M | — |
| 25 | `panel_gate_section_links_to_its_combine_section` (incl. no-evidence link) | unit | RP-14, RP-33 | M×M | — |
| 26 | `ladder_denominator_is_cases_where_the_chain_started` | unit | RP-27 | M×M | — |
| 27 | `budget_spent_grows_down_the_chain_and_refusals_count_per_gate` | unit | RP-28 | M×M | — |
| 28 | `budget_view_differs_flag_renders_and_counts` | unit | RP-35 | M×M | — |
| 29 | `lone_gate_has_no_ladder_line` | unit | RP-26 | M×L | — |
| 30 | `many_labels_show_first_8_and_more_title` | unit | RP-30 | M×L | — |
| 31 | `status_words_are_text_and_dashes_have_titles` | unit | RP-32 | M×L | — |
| 32 | `older_sdk_policy_unknown_decision_key_is_a_version_mismatch` (decode with the pre-E4c key set) | unit | RP-22 | M×L | documents the SDK-first order |
| 33 | `attempt_gates_are_not_shown_or_counted` | unit | RP-29 | L×L | — |
| 34 | `deep_nesting_caps_indent_and_names_level` | unit | RP-31 | L×L | — |
| 35 | `failed_selector_line_says_the_default_branch_ran` (status `failed`, `parse_error` null, title points to the activity view) | unit | RP-7 | M×L | SELECTOR_RECORD render |

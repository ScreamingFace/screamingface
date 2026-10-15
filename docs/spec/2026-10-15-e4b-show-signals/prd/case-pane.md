# PRD: The Combine section in the Case pane

**Source:** ans:Q1 ("Case pane table"), ans:Q2 ("Every reducer step"), ans:Q3 · **Priority:** P0
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §4](../erd.md) · component: [display-format](display-format.md) · contract:
[C2](../contracts.md#c2-case-pane--sdk--notebook-html-static-report-and-live-browser-in-process)

## 1. Summary and user story

As a researcher who opens a Case in the HTML report, I want to see, for each reducer step, what
each member gave, which members were left out and why, the weights, scores, ranks and signals,
and how the step decided, so that I can see why the Case got its answer without writing Python.

## 2. Background and constraints

- The section is "a 'Combine' section in the HTML report's Case detail pane (_pane_html): one row
  per member, plus the step facts (cut, judge model, agreement, tie)". [stated ans:Q1]
- It is shown for every reducer step, also for a plain majority vote with no signal data.
  [stated ans:Q2] (against the recommendation "Only with signal data")
- Numbers: [display-format](display-format.md). [stated ans:Q3]

### 2.1 Current behavior

- `_pane_html(candidate, case, cost_html)` shows the header (case id, verdict, finish, rounds,
  Attempts), the tags, the question, then two views (`case_tabs`): "Answer & grading" holds the
  answer, the refusal, the Attempts, the failures, then the criteria; "Cost & usage" holds the
  cost. It does not read `case.answers()`, `case.trace()` or any `combine` evidence.
  [existing S/_ui/report_view.py:886-952] [existing S/_ui/accounting_view.py:55-68]
- The static report renders at most 25 panes through `bounded_pane`, which falls back to a short
  preview when `case.to_dict()` passes 32,000 characters or the pane passes 24,000 bytes. The live
  browser renders `_pane_html` with no bound. [existing S/_ui/report_view.py:720-807]
- No report-HTML test renders a Case with combine evidence (P18).
- The judge link of a step is in the trace `reduce` entry (`judge_operation_id`, `judge_model`).
  [existing S/_case_views.py:157-171,195-215]

**Delta.** `S/_ui/combine_view.py` gets `combine_sections_html(candidate, case) -> str`.
`_pane_html` puts its result into the "Answer & grading" view, between the failures and the
criteria head:

```python
body = (
    f"{answer_html}{refusal_html}{_attempts_html(case)}{_case_failures_html(case)}"
    f"{combine_sections_html(candidate, case)}{checks_head}{checks}"
)
```

```python
def combine_sections_html(candidate: CandidateResult, case: CaseResult) -> str:
    """One Combine section per combine operation of the Case, in operation order (ans:Q2)."""
    if case.operations is None or all(op.combine is None for op in case.operations):
        return ""
    graph = {info.id: info for info in candidate.operations}
    reduces = {
        entry.data["operation_id"]: entry.data
        for entry in case_trace(case, graph)
        if entry.kind == "reduce"
    }
    return "".join(
        _section(op.operation_id, op.combine, reduces.get(op.operation_id), graph)
        for op in case.operations
        if op.combine is not None
    )
```

`_section` writes exactly this structure (no whitespace between tags):

```text
<div class='sf-cmb'>
  <div class='sf-detail__k' title='{escape(operation_id)}'>combine · {escape(label)}</div>
  <div class='sf-chips'>{chips F1..F10, each <span class='sf-chip'>…</span>}</div>
  <table class='sf-cmb__t'><thead><tr>{th C1..C8}</tr></thead><tbody>{one <tr> per member}</tbody></table>
  {tally table, only when evidence.tally is not None}
</div>
```

- `label` = `graph[operation_id].label` when the id is in the graph, else `operation_id`.
- Chips F1–F10 ([erd §4](../erd.md)). The text of each chip is escaped. F3 is
  `answered · {member_id}` when `result.status == "answered"` and `result.member_id` is set,
  `answered · built` when it is answered with no member, `abstain · {reason}` when it abstained.
  F4 is `cut · top {k} · {order}`. F5 is `reads · {key}`, plus ` · {order}` when the order is set.
  F6 is shown only when the reduce entry exists and its `judge_operation_id` is not None: its text
  is `judge · {escape(judge_model)}`, or `judge · ` + `dash_html("no model recorded for the judge call")`
  when `judge_model` is None. F7 is `agreement · ` + `number_html(agreement, "")`. F8 is `tie · yes`
  or `tie · no`. F9 is `dropped · {dropped}`. F10 is `median · ` + `text_html(median, "")` and
  `mean · ` + `text_html(mean, "")`, each only when set.
- Header cells: `<th>member</th><th>status</th><th>value</th>`, then `<th>weight</th>`,
  `<th>score</th>`, `<th>rank</th>` (each only when at least one row has that value), then one
  `<th>` per signal key (first-seen order over the rows' `signals`), then `<th>chosen</th>`.
  A signal header has `title='{escape(title)}'` when its title is not empty. The title joins, with
  `; `, `source: {declared[key]["source"]}` (when `evidence.declared` has the key) and
  `read by the rule` (when `evidence.signal` reads the key).
- Row: `<tr>` for an answered member, `<tr class='sf-cmb__out'>` for a failed or excluded member.
  Cells: `<td>{member_id}</td>`; status `answered` or `escape(f"{status} · {reason}")`;
  `text_html(row.value, missing_reason(row, "value"))`; `number_html(row.weight, missing_reason(row, "weight"))`;
  `number_html(row.score, missing_reason(row, "score"))`; `str(row.rank)` or
  `dash_html(missing_reason(row, "rank"))`; for each signal key
  `number_html(row.signals.get(key), missing_reason(row, key))`; `<td>&check;</td>` when the member
  id is in `evidence.chosen`, else `<td></td>`.
- Tally table: `<table class='sf-cmb__t'><thead><tr><th>tally value</th><th>score</th><th>holders</th></tr></thead><tbody>`,
  one `<tr><td>{text_html(value, "")}</td><td>{number_html(score, "")}</td><td>{escape(", ".join(holders))}</td></tr>`
  per tally row, `</tbody></table>`.

## 3. Scenarios and acceptance criteria

All oracles use the SDK fixture `ST/data/combine_evidence_cases.json` (through
`_answer_fixtures.evidence_cases()`) or a wire written in the test. Hand-computed.

### 3.1 Happy path

- **CP-1** (ans:Q2) Given `fixture_case("vote_one_failed")` in a Candidate with
  `operations=fixture_graph(3)` (label `synthesis`), then the pane has one section with the heading
  `combine · synthesis`; the chips are exactly
  `<span class='sf-chip'>reducer · vote</span><span class='sf-chip'>rule · last_number@1 → numeric@1 → mode@1 → first_holder@1</span><span class='sf-chip'>answered · member_1</span><span class='sf-chip'>agreement · <span class='sf-cmb__n' title='1.0'>1</span></span><span class='sf-chip'>tie · no</span><span class='sf-chip'>dropped · 1</span>`;
  the header is `<tr><th>member</th><th>status</th><th>value</th><th>chosen</th></tr>`; the rows
  are `<tr><td>member_1</td><td>answered</td><td>42</td><td>&check;</td></tr>`,
  `<tr class='sf-cmb__out'><td>member_2</td><td>fail · empty</td><td><span class='sf-cmb__na' title='member failed: empty'>—</span></td><td></td></tr>`,
  `<tr><td>member_3</td><td>answered</td><td>42</td><td></td></tr>`; the tally row is
  `<tr><td>42</td><td><span class='sf-cmb__n' title='2.0'>2</span></td><td>member_1, member_3</td></tr>`.
- **CP-2** Given `fixture_case("vote_field_signal")` (graph `fixture_graph(3)`), then the header is
  `<tr><th>member</th><th>status</th><th>value</th><th>weight</th><th title='read by the rule'>field:confidence</th><th>chosen</th></tr>`;
  member_1 has the weight cell `<span class='sf-cmb__n' title='0.9'>0.9</span>`; the chips have
  `reads · field:confidence` (no order) and `agreement · <span class='sf-cmb__n' title='0.5625'>0.5625</span>`;
  the tally rows are `a` with `0.9` and `b` with `0.7`, holders `member_2, member_3`.
- **CP-3** Given a judge reducer step whose judge call has `request_model="provider/judge-x"`, then
  the chips have `<span class='sf-chip'>judge · provider/judge-x</span>`. [stated ans:Q1]
- **CP-4** Given a declared signal (part 3), then its header names its source. Wire: the
  `vote_field_signal` wire with `signals` `{"conf": 90.0}`, `{"conf": 30.0}`, `{"conf": 40.0}`,
  `signal` `{"key": "conf", "order": null}` and
  `declared` `{"conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}}` (as
  `ST/test_declared_signals.py:281-288`). The header cell is
  `<th title='source: verbalized; read by the rule'>conf</th>`; member_1's cell is
  `<span class='sf-cmb__n' title='90.0'>90</span>`. [stated ans:Q1] (epic A3)
- **CP-5** Given the `rank_cut_not_met` wire (§7), then the header is
  `<tr><th>member</th><th>status</th><th>value</th><th>score</th><th>rank</th><th title='read by the rule'>field:score</th><th>chosen</th></tr>`;
  the chips have `abstain · cut_not_met`, `cut · top 3 · max`, `reads · field:score · max`;
  member_2's row is `<tr class='sf-cmb__out'><td>member_2</td><td>excluded · no_signal</td>`
  then a value dash with title `left out by the rule: no_signal`, then score, rank and
  `field:score` dashes with the same title; member_1's rank cell is `<td>2</td>` and member_3's is
  `<td>1</td>`; member_1's value cell is a dash with title `no value recorded`; no `&check;`.

### 3.2 Error paths

- **CP-E1** Given a judge step whose judge call has no accounting, then the judge chip is
  `<span class='sf-chip'>judge · <span class='sf-cmb__na' title='no model recorded for the judge call'>—</span></span>`.
  [existing S/_case_views.py:213-215]
- **CP-E2** Given a step that reads no judge (`vote_one_failed`), then the section has no
  `judge ·`. [existing S/_case_views.py:208-209]
- **CP-E3** Given a member value `<img src=x onerror=evil()>`, an operation label `a<b>` and a judge
  model `provider/<model>`, then the pane holds `&lt;img src=x onerror=evil()&gt;`, `a&lt;b&gt;` and
  `provider/&lt;model&gt;`, and does not hold `<img`, `a<b>` or `provider/<model>`. [proposed] P8

### 3.3 Derived scenarios (risk-ordered)

- **CP-D1** (H×M) [proposed] P18 Given a Case without combine evidence (no operations, or operations
  without `combine`), then the pane has no `sf-cmb` and no `combine ·`.
- **CP-D2** (M×M) [stated ans:Q2] Given a Case with two combine operations (`op_synthesis_1`
  `vote_one_failed`, then `op_synthesis_2` `median_nearest`, label `outer`), then the pane has two
  sections, `combine · synthesis` before `combine · outer`.
- **CP-D3** (M×M) [proposed] P10 Given a Case with an answer, a criterion and combine evidence, then
  in the pane `sf-answer-view` < the answer < `combine ·` < the criteria head < `sf-cost-view`.
- **CP-D4** (M×M) [proposed] P11 Given `vote_one_failed`, then no `<th>weight</th>`,
  `<th>score</th>` or `<th>rank</th>`; given the CP-4 wire plus a second declared name `ent`
  (`{"source": "entropy", "top_logprobs": 5}`) with member_3 `ent: null`, then `<th title='source: entropy'>ent</th>`
  is shown and member_3's cell has the title `no ent recorded`.
- **CP-D5** (L×M) [proposed] P16 Given `median_value` (built, `median` `"20"`), then the chips have
  `answered · built` and `median · 20`; given `median_nearest`, the agreement chip shows
  `<span class='sf-cmb__n' title='0.3333333333333333'>0.3333</span>`.
- **CP-D6** (M×L) [existing] Given a 256-member vote wire (each value `"x" * 50`), then
  `bounded_pane` returns the short preview (no `sf-cmb`), and `_pane_html` shows the section with 256
  member rows. [existing S/_ui/report_view.py:798-807] N3
- **CP-D7** (L×L) [proposed] P9 The pane adds no `<style` tag.

## 4. Non-functional requirements

- O(members × signal keys) per step; one `case_trace` call per pane. [proposed]
- The section never raises for evidence that the SDK decoder accepted. [proposed]

## 5. Out of scope

- The merge `fields` readings, the judge reading text and `presentation_order` /
  `separator_collision` (D2). [proposed]
- Member display names (D3). Combine steps in Attempts (D1).
- Sorting, filtering or folding the table. [proposed]

## 6. Open questions

None.

## 7. TDD plan

Test file: `ST/test_combine_case_pane.py` (new). Render with
`_pane_html(candidate, case, "")` (and `bounded_pane` for row 16). Build the Candidate with a copy of
`ST/test_report_trace.py:114-139` (`_candidate`) that takes `operations` and `cases`. Do not bind a
Case to a graph yourself: a bound Case keeps its first graph (S/case_result.py:645-650), and the
view reads the Candidate graph. For the judge rows, build the graph `op_model_1..3` (model),
`op_judge_1` (judge, depends on the members), `op_synthesis_1` (combine, depends on the members and
`op_judge_1`), the Case operations as `ST/test_judge_link_trace.py:188-215` does, and the evidence
from `ST/test_judge_link_trace.py:60-74` (`_judge_scores()`, importable). For the criterion of row 14,
use the `Check` of `ST/test_criterion_chip_passfail.py:27-35`.

The `rank_cut_not_met` wire (copy into the test; the Engine file is
`ET/data/combine_contract/evidence_cases.json`):

```json
{"schema": "screamingface.combine-evidence.v1", "kind": "selection", "reducer": "rank",
 "operators": ["by_signal@1", "top_k@1"],
 "members": [
  {"member_id": "member_1", "raw": null, "value": null, "status": "answered", "reason": null,
   "signals": {"field:score": 0.3}, "weight": null, "score": 0.3, "rank": 2},
  {"member_id": "member_2", "raw": null, "value": null, "status": "excluded", "reason": "no_signal",
   "signals": {"field:score": null}, "weight": null, "score": null},
  {"member_id": "member_3", "raw": null, "value": null, "status": "answered", "reason": null,
   "signals": {"field:score": 0.6}, "weight": null, "score": 0.6, "rank": 1}],
 "tally": null, "judge": null, "fields": null, "chosen": [], "built": false, "agreement": null,
 "tie": false, "median": null, "presentation_order": null, "separator_collision": null,
 "signal": {"key": "field:score", "order": "max"}, "cut": {"k": 3, "order": "max"},
 "result": {"member_id": null, "value": null, "status": "abstain", "reason": "cut_not_met"},
 "dropped": 0, "finish_reason": "stop"}
```

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `pane_without_combine_evidence_has_no_combine_markup` | unit | CP-D1 | H×M | passes today and after |
| 2 | CHAR `pane_keeps_answer_before_criteria_in_the_answer_view` | unit | [existing S/_ui/report_view.py:936-952] | M×L | passes today and after |
| 3 | `plain_majority_vote_shows_its_combine_section` | unit | CP-1 (ans:Q2) | M×M | `combine_sections_html`, `_section` |
| 4 | `failed_member_row_shows_its_status_and_a_dashed_value` | unit | CP-1 | M×H | MR-1, `sf-cmb__out` |
| 5 | `weighted_vote_shows_the_weight_and_signal_columns` | unit | CP-2 | M×M | P11 |
| 6 | `rank_step_shows_score_rank_cut_and_the_excluded_member` | unit | CP-5 | M×M | F3, F4, F5, MR-2 |
| 7 | `declared_signal_header_names_its_source` | unit | CP-4 | M×M | header title |
| 8 | `declared_signal_that_no_rule_reads_keeps_its_column` | unit | CP-D4 | M×M | P11 |
| 9 | `judge_step_names_the_judge_model` | unit | CP-3 | M×M | F6 from the reduce entry |
| 10 | `judge_step_without_accounting_shows_a_dash` | unit | CP-E1 | M×L | F6 dash |
| 11 | `step_without_a_judge_has_no_judge_chip` | unit | CP-E2 | M×L | F6 guard |
| 12 | `member_text_label_and_judge_model_are_escaped` | unit | CP-E3 | H×M | P8 |
| 13 | `two_combine_steps_show_two_sections_in_operation_order` | unit | CP-D2 | M×M | loop over `case.operations` |
| 14 | `section_sits_between_the_answer_and_the_criteria` | unit | CP-D3 | M×M | `body` order in `_pane_html` |
| 15 | `median_text_and_built_result_are_shown_as_stored` | unit | CP-D5 | L×M | F3, F7, F10 |
| 16 | `large_section_falls_back_in_the_preview_and_shows_live` | unit | CP-D6 | M×L | no new bound |
| 17 | `pane_adds_no_style_tag` | unit | CP-D7 | L×L | style lives in `_STYLE` |

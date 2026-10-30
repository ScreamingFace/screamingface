# PRD: Show the gate (Case pane, run summary, export)

**Source:** ans:Q1 ("records the comparison and the branch"); part 4 ans:Q1–Q3 (the surfaces and the
number format) · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §6](../erd.md) · component: [gate-record](gate-record.md) · surfaces of part 4:
docs/spec/2026-10-15-e4b-show-signals/prd/case-pane.md, run-summary.md, export-trace.md

## 1. Summary and user story

As a researcher who opens a Case in the HTML report, I want to see the gate of a vote: the number it
compared, the comparison, the threshold and the branch it took; and in the Candidate card, how often
the gate kept the majority. I want the JSON export to hold the same record, so that a reader without
the SDK can replay the decision.

## 2. Background and constraints

- Part 4 §8: "E4b part 5 (gates) can show its gate record in the same Combine section."
  [stated part 4 spec]
- Numbers: 4 significant digits, the exact value on hover, a missing value is an em dash with its
  reason. [stated part 4 ans:Q3]
- The report-trace.v1 field set is pinned (ST/test_judge_link_trace.py:430-451,
  ST/test_e4b_schema_pins.py:24-25). A `branch` trace kind is E4c's report-trace.v2. [existing]; P16

### 2.1 Current behavior

- `_chips` (S/_ui/combine_view.py:176-193) writes the step facts F1–F10: reducer, rule, result, cut,
  reads, judge, agreement, tie, dropped, median, mean.
- `_StepSummary.add` (:306-321) counts chosen and excluded per member and keeps the declared-signal
  values. `_summary_html` (:323-338) writes the heading, then one table.
- `_reads_judge` (S/_case_views.py:181-192) has the rules J1–J3. `_judge_link` (:195-215) links the
  one `judge` operation in the combine node's `depends_on`; two or more give null (:210-212).
- The report export already writes `operations[].combine` with `CombineEvidence.to_dict()`
  (S/case_result.py:333-336), so a decoded gate record is exported with no export change.

**Delta.**

- `S/_ui/combine_view.py`:
  - `_chips` puts `_gate_chip(evidence.gate)` right after the agreement chip and before the tie chip.
  - New `_gate_chip(gate: CombineGate | None) -> str` (empty string when `gate is None`):

    ```python
    head = escape(f"gate · {gate.observe} {gate.cmp} ") + number_html(gate.threshold, "")
    observed = number_html(gate.observed, _GATE_NOT_RUN if gate.passed is None else _GATE_NO_NUMBER)
    return f"{head} · observed {observed} · {escape(_gate_verdict(gate))}"
    ```

    `_GATE_NOT_RUN = "the vote found no answer, so the gate did not run"`,
    `_GATE_NO_NUMBER = "no number to compare, so the gate took the fallback"`.
    `_gate_verdict`: `passed is True` → `majority`; `passed is False` → `fallback · {otherwise}`;
    `passed is None` → `not run`.
  - `_StepSummary` gets `gated: int`, `majority: int`, `fallback: int`, `not_run: int` (all 0).
    `add` counts a Case with `evidence.gate` once in `gated`, and once in the counter of its
    `passed` value (True → `majority`, False → `fallback`, None → `not_run`).
  - `_summary_html` writes `_gate_line(step)` between the heading and the table, only when
    `step.gated > 0`:
    `<div class='sf-chips'><span class='sf-chip'>gate · majority {m} of {N} · fallback {f} of {N}{tail}</span></div>`,
    where `N = step.cases` and `tail = f" · not run {r} of {N}"` when `r > 0`, else `""`.
- `S/_case_views.py`: `_reads_judge` gets rule J4: `evidence.gate is not None and
  evidence.gate.branch == "fallback" and evidence.gate.otherwise == "judge"`. The link rule itself
  does not change.
- No change to `S/report.py`, `S/_report_export.py`, `report_trace.py` or any schema.

## 3. Scenarios and acceptance criteria

The wires are the five Engine gate cases of [gate-decision](gate-decision.md) GD-D9. The tests
read them from `COMBINE_CONTRACT / "evidence_cases.json"` (`_combine_contract.COMBINE_CONTRACT`)
under `@requires_engine_app`, decode each with `decode_combine_evidence`, and build the Case by
hand like `ST/test_member_exclusion.py:_case` (or `ST/test_frozen_record_fields.py:_fixture_case`):
one `CaseOperation` per member, one combine operation that holds the evidence, then
`bound(case, graph)`. Do NOT use `_answer_fixtures.fixture_case`: it reads the SDK-local copy
`ST/data/combine_evidence_cases.json`, which holds only five E4a cases. Do NOT edit
`ST/data/combine_evidence_cases.json`. Their numbers: tally `9: 2.0`, `12: 1.0`, agreement
`0.6666666666666666`.

### 3.1 Happy path

- **GS-1** Given `vote_gate_majority` (`{agreement, >=, 0.6, abstain}`, passed), then the section
  has exactly one chip `<span class='sf-chip'>gate · agreement &gt;= <span class='sf-cmb__n'
  title='0.6'>0.6</span> · observed <span class='sf-cmb__n' title='0.6666666666666666'>0.6667</span>
  · majority</span>` (written with no line break), placed right after the agreement chip and before
  `<span class='sf-chip'>tie · no</span>`. [stated ans:Q1]
- **GS-2** Given `vote_gate_abstain` (threshold 0.7), then the gate chip ends with
  `· fallback · abstain</span>` and has `title='0.7'>0.7</span>`, and the result chip is
  `<span class='sf-chip'>abstain · gate_not_met</span>`. [stated ans:Q3]
- **GS-3** Given `vote_gate_judge` and a Candidate graph whose combine node depends on one `judge`
  operation `op_judge_1` with the request model `provider/judge-x`, then the gate chip ends with
  `· fallback · judge</span>`, the result chip is `answered · member_3`, and the section has the
  chip `judge · provider/judge-x` (rule J4). [proposed] P16
- **GS-4** Given `vote_gate_writer`, then the gate chip ends with `· fallback · writer</span>` and
  the result chip is `answered · built`. [stated ans:Q3]
- **GS-5** Given one Candidate with three Cases of one gated step (`vote_gate_majority`,
  `vote_gate_abstain`, `vote_gate_not_run`), then the run summary of that step has
  `<span class='sf-chip'>gate · majority 1 of 3 · fallback 1 of 3 · not run 1 of 3</span>` right
  after its heading and before its table. [proposed] P16

### 3.2 Error paths

- **GS-E1** Given any gate record, then the comparison text is escaped: `>=` shows as `&gt;=`,
  `<` as `&lt;`, and no raw `<` or `>` from the record reaches the page outside the markup.
  [existing part 4 P8]

### 3.3 Derived scenarios (risk-ordered)

- **GS-D1** (H×M) [proposed] Given `vote_gate_not_run`, then the gate chip is
  `gate · agreement &gt;= <span class='sf-cmb__n' title='0.6'>0.6</span> · observed
  <span class='sf-cmb__na' title='the vote found no answer, so the gate did not run'>—</span> · not run`
  inside its chip span.
- **GS-D2** (H×M) [proposed] Given a copy of the `vote_gate_abstain` wire with
  `declared = {"conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}}`, every member
  `signals = {"conf": null}`, and `gate.observe = "mean:conf"`, `gate.observed = null`, then the
  observed cell is `<span class='sf-cmb__na' title='no number to compare, so the gate took the
  fallback'>—</span>`.
- **GS-D3** (H×M) [existing part 4 CP#1, RS#1] Given any ungated evidence (the 32 cases of the fixed
  list L32, test-plan §6, never a loop over the whole file),
  then the section and the run summary are byte-equal to what they are on `4e622af75`: no gate chip,
  no gate line.
- **GS-D4** (H×M) [existing S/case_result.py:333-336] Given a report with the `vote_gate_judge` Case,
  then `report.to_dict()` and the streamed `report.export()` both hold
  `operations[<combine>].combine.gate == {"observe": "agreement", "observed": 0.6666666666666666,
  "cmp": ">=", "threshold": 0.7, "passed": false, "branch": "fallback", "otherwise": "judge"}`, and
  every trace `reduce` entry has exactly the 11 keys of `TRACE_FIELDS["reduce"]`.
- **GS-D5** (M×M) [proposed] P16, N4 Given `vote_gate_judge` in a Case, then its trace `reduce` entry
  has `judge_operation_id = "op_judge_1"` and `judge_model = "provider/judge-x"` (J4). Given
  `vote_gate_majority` with the same graph, then both are null (the judge was not read). Given a
  graph with two `judge` operations, then both are null (N4).

## 4. Non-functional requirements

- The summary still reads each Case once (part 4 N4). [existing]
- No new style rule: the gate chip and line use `.sf-chip` and `.sf-chips`. [proposed]

## 5. Out of scope

- A trace entry of its own for the gate, or the "stages that did not run" (E4c, report-trace.v2).
- A Python accessor for the gate besides `CombineEvidence.gate` (part 4 ans:Q1 precedent).

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the ungated surfaces, then the chip for each branch, then the summary, then the
export and the trace link. New test file: `ST/test_gate_display.py`. The Engine-fixture tests are
marked `requires_engine_app` and read `COMBINE_CONTRACT / "evidence_cases.json"` with a hand-built
Case (§3); they never use `_answer_fixtures.fixture_case` and never edit
`ST/data/combine_evidence_cases.json`. This unit has no pinned file.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `ungated_section_and_summary_are_unchanged` | unit | GS-D3 | H×M | passes today |
| 2 | `case_pane_shows_the_gate_chip_after_agreement` | unit | GS-1 | H×H | `_gate_chip` in `_chips` |
| 3 | `case_pane_shows_the_abstain_fallback` | unit | GS-2 | H×M | `_gate_verdict` |
| 4 | `case_pane_shows_the_fallback_judge_and_its_model` | unit | GS-3 | H×M | rule J4 |
| 5 | `case_pane_shows_the_writer_fallback_as_built` | unit | GS-4 | M×M | — |
| 6 | `case_pane_shows_a_gate_that_did_not_run` | unit | GS-D1 | H×M | `_GATE_NOT_RUN` |
| 7 | `missing_observed_number_is_a_dash_with_its_reason` | unit | GS-D2 | H×M | `_GATE_NO_NUMBER` |
| 8 | `gate_chip_escapes_the_comparison` | unit | GS-E1 | H×M | `escape` |
| 9 | `run_summary_counts_majority_fallback_and_not_run` | unit | GS-5 | H×M | `_StepSummary`, `_gate_line` |
| 10 | `run_summary_has_no_gate_line_for_an_ungated_step` | unit | GS-D3 | M×M | `gated > 0` |
| 11 | `export_holds_the_gate_record_and_the_trace_fields_stay` | unit | GS-D4 | H×M | no change expected |
| 12 | `trace_links_the_fallback_judge_only_when_it_was_read` | unit | GS-D5 | M×M | J4 |

# PRD: The run summary of each reducer step in the Candidate card

**Source:** ans:Q1 ("Run-level summary") · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §5](../erd.md) · component: [display-format](display-format.md) · contract:
[C3](../contracts.md#c3-candidate-card--sdk--notebook-html-in-process)

## 1. Summary and user story

As a researcher who compares recipes, I want each Candidate card to say, for each reducer step,
how often each member was chosen and left out, and the mean of each declared signal, so that I can
see which members carry the result and how sure they were, over the whole run.

## 2. Background and constraints

- Owner option text: "per candidate in the report card: how often each member was excluded or
  chosen, and the mean of each declared signal." [stated ans:Q1]
- "Hide the block when a candidate has no reducer step." [stated prompt]
- Numbers: [display-format](display-format.md). [stated ans:Q3]

### 2.1 Current behavior

- `_card_html` shows the name, the context line (with ` · N abstained` when N > 0), the models,
  the figures grid, the coverage notice, the named scores, the axes, the grading warning, the
  members block, the accounting note and the folded URL4 block. [existing S/_ui/report_view.py:337-394]
- `abstained_count` already reads every Case of the Candidate. [existing S/report.py:465-468]
- No card block reads `combine` evidence.

**Delta.** `S/_ui/combine_view.py` gets `combine_summary_html(candidate) -> str`. `_card_html`
puts it directly after `_members_html(candidate)` and before `run_accounting_note(...)`.
[proposed] P13

```python
def combine_summary_html(candidate: CandidateResult) -> str:
    """Per reducer step: chosen and excluded counts, and declared-signal means (ans:Q1)."""
    steps: dict[str, _StepSummary] = {}
    for case in candidate.cases:
        for operation in case.operations or ():
            if operation.combine is not None:
                steps.setdefault(operation.operation_id, _StepSummary(operation.combine.reducer)).add(
                    operation.combine
                )
    if not steps:
        return ""
    graph = {info.id: info for info in candidate.operations}
    blocks = "".join(_summary_html(operation_id, step, graph) for operation_id, step in steps.items())
    return f"<div class='sf-detail__k'>combine</div><div class='sf-cmb'>{blocks}</div>"
```

`_StepSummary` (a private dataclass) keeps: `reducer: str`; `cases: int`; `chosen: dict[str, int]`
and `excluded: dict[str, int]` (member id → count, insertion order = first seen);
`declared: dict[str, str]` (name → source, first seen); `values: dict[tuple[str, str], list[float]]`
((member id, signal name) → the non-None values). `add(evidence)` adds 1 to `cases`; adds each
`evidence.declared` name with `str(entry["source"])` when it is new; and for each member row: sets
both counts to 0 when new, adds 1 to `chosen` when `row.member_id in evidence.chosen`, adds 1 to
`excluded` when `row.status == "excluded"`, and appends each non-None `row.signals` value.

`_summary_html` writes (no whitespace between tags), with `_label` and `_table` of
[case-pane](case-pane.md) §2 (P20):

```text
<div class='sf-cmb__h' title='{escape(operation_id)}'>{escape(_label(graph, operation_id))} · {escape(reducer)} · {N} case|cases</div>
{_table(head, rows)}, where
  head = <th scope='col'>member</th><th scope='col'>chosen</th><th scope='col'>excluded</th>
         {<th scope='col' title='{escape("source: " + source)}'>{escape(name)} mean</th> per declared name}
  rows = {<tr><td>{escape(member)}</td><td>{chosen} of {N}</td><td>{excluded} of {N}</td>{mean cells}</tr> per member}
```

- `case` when N == 1, else `cases`. `chosen` and `excluded` both show `{count} of {N}`, so the two
  columns read the same way (P13).
- A mean cell is `<td>` + `number_html(mean, "no Case gave a value")` + ` <span class='sf-cmb__nn'>n={n}</span></td>`,
  where `n` = the number of values and `mean = math.fsum(values) / n` (None when n == 0).

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **RS-1** Given three Cases of one weighted vote (`op_synthesis_1`, label `synthesis`) that
  declares `conf` (`{"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}`), with these rows
  (status, value, conf) and chosen member:

  | Case | member_1 | member_2 | member_3 | chosen |
  |---|---|---|---|---|
  | 1 | answered, `a`, 90.0 | answered, `b`, 60.0 | excluded `no_weight`, `b`, None | member_1 |
  | 2 | answered, `a`, 80.0 | answered, `b`, 70.0 | answered, `b`, 50.0 | member_2 |
  | 3 | answered, `a`, 70.0 | fail `empty`, None, None | answered, `b`, 40.0 | member_1 |

  then the block is `<div class='sf-detail__k'>combine</div>`, the heading is
  `<div class='sf-cmb__h' title='op_synthesis_1'>synthesis · vote · 3 cases</div>`, the header is
  `<tr><th scope='col'>member</th><th scope='col'>chosen</th><th scope='col'>excluded</th><th scope='col' title='source: verbalized'>conf mean</th></tr>`,
  and the rows are exactly:
  `<tr><td>member_1</td><td>2 of 3</td><td>0 of 3</td><td><span class='sf-cmb__n' title='80.0'>80</span> <span class='sf-cmb__nn'>n=3</span></td></tr>`,
  `<tr><td>member_2</td><td>1 of 3</td><td>0 of 3</td><td><span class='sf-cmb__n' title='65.0'>65</span> <span class='sf-cmb__nn'>n=2</span></td></tr>`,
  `<tr><td>member_3</td><td>0 of 3</td><td>1 of 3</td><td><span class='sf-cmb__n' title='45.0'>45</span> <span class='sf-cmb__nn'>n=2</span></td></tr>`.
  Hand-computed: member_1 (90+80+70)/3 = 80; member_2 (60+70)/2 = 65; member_3 (50+40)/2 = 45.
  [stated ans:Q1]
- **RS-2** Given two Cases where member_1 has conf 0.1 and 0.2, then its mean cell shows
  `<span class='sf-cmb__n' title='0.15000000000000002'>0.15</span> <span class='sf-cmb__nn'>n=2</span>`
  (`math.fsum([0.1, 0.2]) / 2 == 0.15000000000000002`). [stated ans:Q3]
- **RS-3** Given the Cases `vote_one_failed` and `vote_abstain` (no declared signal), then the header
  is `<tr><th scope='col'>member</th><th scope='col'>chosen</th><th scope='col'>excluded</th></tr>`,
  the heading ends `synthesis · vote · 2 cases`, member_1 shows `1 of 2`, member_2 and member_3 show
  `0 of 2`, and every `excluded` cell is `0 of 2`. [stated ans:Q1] (ans:Q2: every reducer step)

### 3.2 Error paths

- **RS-E1** Given a declared name `ent` with no value in any Case, then its mean cell is
  `<td><span class='sf-cmb__na' title='no Case gave a value'>—</span> <span class='sf-cmb__nn'>n=0</span></td>`.
  [stated ans:Q3]
- **RS-E2** Given a Candidate with no combine evidence in any Case, then `combine_summary_html`
  returns `""` and the card has no `sf-cmb`. [stated prompt]

### 3.3 Derived scenarios (risk-ordered)

- **RS-D1** (H×M) [proposed] P8 Given the label `a<b>` and a declared source `<x>`, then the card
  holds `a&lt;b&gt;` and `title='source: &lt;x&gt;'`, and not `a<b>` or `<x>`.
- **RS-D2** (M×M) [proposed] P13 Given the graph and the Case of [case-pane](case-pane.md) CP-D2
  (`op_synthesis_1` label `synthesis` with `vote_one_failed`, then `op_synthesis_2` label `outer`
  with `median_nearest`), then there are two headings, `synthesis` first.
- **RS-D3** (M×M) [proposed] P15 Given a model-only Case, an Attempts Case (operations only on the
  Attempts) and one combine Case, then the heading says `1 case`.
- **RS-D4** (M×L) [proposed] P13 Given a combine Candidate, then in the card
  `sf-report__grid` < `<div class='sf-detail__k'>combine</div>` < `<summary>URL4</summary>`.
- **RS-D5** (L×L) [proposed] Given one Case, then the heading ends `· 1 case` (singular).

## 4. Non-functional requirements

- One pass over `candidate.cases`; memory O(steps × members × signal names), not O(Cases). N4.
- Integer counts show as integers; only the means use the 4-digit format. [proposed] P5

## 5. Out of scope

- E4a signal means (`cost_usd`, `field:<path>`, `score:judge`) in the summary (P14). They show per
  Case in the Combine section.
- A failed-member count, an abstain count per step (the card context line already has the
  Candidate abstain count). [proposed]
- Attempts (D1), member display names (D3).

## 6. Open questions

None.

## 7. TDD plan

RED stub: `combine_summary_html` returns `""` (it does not raise). Wire its call into `_card_html`
in the GREEN commit, so RS#1, RS#2 and the existing report-HTML tests stay green in the RED commit.

Test file: `ST/test_combine_run_summary.py` (new). Render the card with
`_card_html(candidate, report)` and the block with `combine_summary_html(candidate)`. Build the
Candidate with a copy of `ST/test_report_trace.py:114-139` (`_candidate`) that takes `operations`
and `cases` (graph: `fixture_graph(3)`). Build each RS-1 Case wire from the SDK `vote_field_signal`
wire: operators `["json_field@1", "text@1", "weighted_mode@1", "max_weight_holder@1"]`; each member
`{"member_id", "raw": value, "value": value, "status", "reason", "signals": {"conf": conf},
"weight": conf if status == "answered" else None, "score": None}`; `tally: null`,
`agreement: null`, `chosen: [chosen]`, `result` the chosen member and its value,
`signal: {"key": "conf", "order": null}`, the `declared` map above, `dropped` = the number of
failed rows. Decode it with `decode_combine_evidence(wire, "ev")`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `card_without_combine_evidence_has_no_summary` | unit | RS-E2 | H×M | passes today and after |
| 2 | CHAR `card_shows_the_grid_before_the_url4_block` | unit | [existing S/_ui/report_view.py:381-394] | L×L | passes today and after |
| 3 | `summary_counts_chosen_excluded_and_means_the_declared_signal` | unit | RS-1 | M×H | `_StepSummary`, `_summary_html` |
| 4 | `mean_title_shows_the_exact_value` | unit | RS-2 | M×M | `math.fsum`, `number_html` |
| 5 | `summary_without_declared_signals_shows_chosen_and_excluded_only` | unit | RS-3 | M×M | no mean columns |
| 6 | `signal_with_no_value_in_any_case_shows_a_dash_and_n_zero` | unit | RS-E1 | M×M | `number_html(None, …)` |
| 7 | `labels_and_sources_are_escaped` | unit | RS-D1 | H×M | P8 |
| 8 | `two_steps_give_two_blocks_in_first_seen_order` | unit | RS-D2 | M×M | dict insertion order |
| 9 | `cases_without_case_operations_are_ignored` | unit | RS-D3 | M×M | `case.operations or ()` |
| 10 | `summary_sits_after_the_grid_and_before_the_url4_block` | unit | RS-D4 | M×L | `_card_html` order |
| 11 | `one_case_heading_is_singular` | unit | RS-D5 | L×L | `case` / `cases` |

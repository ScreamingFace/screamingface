# PRD: Show the sum and the band in the report (part 4 surfaces)

**Source:** ans:Q1 ("recorded like any declared signal"), ans:Q2 ("recorded in the gate record");
epic "The report shows it and the source" · **Priority:** P1
**Lifecycle:** existing (characterize + delta on the part 4 and part 5 display)
**Owner:** unassigned
Paths: [erd §6](../erd.md) · contracts: C5 · uses: [signal-sum](signal-sum.md),
[abstain-band](abstain-band.md)

## 1. Summary and user story

As a benchmark author who opens a Case or a run summary, I see the sum as one more signal column
whose header names its formula, I see the band in the gate chip, and I see how many Cases abstained
in the band, so that I can check each decision without reading the raw evidence.

## 2. Background and constraints

- Part 4 shows every declared name as a signal column (S/_ui/combine_view.py:153-176). A sum needs
  no new column code: it is a declared name in `members[].signals`. [existing]
- The part 5 gate chip regex of `ST/test_gate_display.py:51` allows only text and inner number
  spans in a chip. The band chip keeps that shape. [existing]
- The part 5 display tests pin the render of the base cases by digest. Each existing case must keep
  its bytes. [existing ST/test_gate_display.py:53-]

### 2.1 Current behavior

- `_signal_head` (S/_ui/combine_view.py:240-250): the title is `source: {entry["source"]}`, then
  `read by the rule` when the step reads the key.
- `_gate_chip` (:223-230): `gate · {observe} {cmp} {threshold} · observed {observed} · {verdict}`;
  the observed reason is `_GATE_NOT_RUN` when `passed is None`. `_gate_verdict` (:233-237):
  `passed is None` → `not run`.
- `_StepSummary` (:317-358): `declared` maps a name to `str(entry["source"])`; `_add_gate` counts
  `passed is None` as not run. `_gate_line` (:378-389). `_summary_html` (:361-375) writes the
  header title `source: {source}`. `_mean_cell` (:401-408) uses `math.fsum(values) / count`, which
  raises `OverflowError` for `[1e308, 1e308]`.
- The JSON export writes the evidence `to_dict()` in `operations[].combine` (S/case_result.py). [existing]

**Delta (SDK, `S/_ui/combine_view.py` only).**

```python
def _source_text(entry: Mapping[str, object]) -> str:
    """The source words of one declared entry: "sum of 0.5 × sev_a + 0.3 × sev_b" for a sum whose
    coefficients are a mapping of names to numbers; else str(entry["source"]) (today's text)."""
# term text: f"{float(value)!r} × {name}", joined by " + ", in the entry order.

# _signal_head: notes.append(f"source: {_source_text(evidence.declared[key])}")
# _StepSummary.add: self.declared.setdefault(name, _source_text(entry))

def _gate_chip(gate): # head, then " · band [" + number_html(lo, "") + ", " + number_html(hi, "")
                      # + "]" when the band is set, then " · observed ... · {verdict}".
                      # The observed reason is _GATE_NOT_RUN when branch is None.
def _gate_verdict(gate): # branch None -> "not run"; "band" -> "in band · abstain";
                         # "majority" -> "majority"; "fallback" -> f"fallback · {otherwise}".
# _StepSummary: new counter `band`; _add_gate counts branch None as not run, "band" as band.
# _gate_line: "... · fallback {f} of {N}" + (" · in band {b} of {N}" if b) + (" · not run ..." if r).
# _mean_cell: math.fsum(values) / count; on OverflowError the exact Fraction mean, rounded once
#   (the part 5 erratum E6 rule, E/combine/gate.py:61-70). Add one WHY comment in _mean_cell
#   that names E/combine/gate.py `_mean` as its twin, so a later edit changes both copies.
```

## 3. Scenarios and acceptance criteria

The oracles use the helpers of `ST/test_gate_display.py`: `_N(title, text)` =
`<span class='sf-cmb__n' title='{title}'>{text}</span>`, `_AGREEMENT` = `_N("0.6666666666666666",
"0.6667")`, `_chip(text)` = `<span class='sf-chip'>{text}</span>`.

### 3.1 Happy path

- **SD-1** Given the contract case `pick_sum_min`, then the Case pane member table header holds
  `<th scope='col' title='source: sum of 0.5 × sev_a + 0.3 × sev_b; read by the rule'>risk</th>`
  and `<th scope='col' title='source: verbalized'>sev_a</th>`; the member_3 `risk` cell is the
  dash with the title `left out by the rule: no_signal`. [stated ans:Q1]; [proposed] P14
- **SD-2** Given a run summary over the case `pick_sum_min`, then the header holds
  `<th scope='col' title='source: sum of 0.5 × sev_a + 0.3 × sev_b'>risk mean</th>`. [proposed] P14
- **SD-3** Given the contract case `vote_gate_band`, then the gate chip is
  `_chip("gate · agreement &gt;= " + _N("0.7", "0.7") + " · band [" + _N("0.6", "0.6") + ", " +
  _N("0.7", "0.7") + "] · observed " + _AGREEMENT + " · in band · abstain")`, and the result chip
  is `_chip("abstain · in_band")`. [stated ans:Q2]; [proposed] P14
- **SD-4** Given a run summary over the cases `vote_gate_majority`, `vote_gate_abstain` and
  `vote_gate_band`, then the gate line is `_chip("gate · majority 1 of 3 · fallback 1 of 3 · in
  band 1 of 3")`. Over `vote_gate_band`, `vote_gate_not_run` and `vote_gate_majority`, it is
  `_chip("gate · majority 1 of 3 · fallback 0 of 3 · in band 1 of 3 · not run 1 of 3")`.
  [proposed] P14
- **SD-5** Given the JSON export of a Case whose combine operation has the `vote_gate_band`
  evidence, then `operations[0]["combine"]["gate"]["abstain_band"] == [0.6, 0.7]` and
  `operations[0]["combine"]["result"]["reason"] == "in_band"`. [existing export]; [stated ans:Q2]

### 3.2 Error paths

- **SD-E1** Given a hand-built evidence whose `declared` entry is `{"source": "sum"}` (no
  coefficients) or `{"source": "sum", "coefficients": ["a"]}`, then the header title is
  `source: sum` (no error). [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **SD-D1** (H×M) [implied] Every case of list L37 renders the same Combine section and run summary
  bytes as on base `633fec3a1` (sha256 digests taken on base at RED time, written as a literal
  dict, the `ST/test_gate_display.py` L32 precedent).
- **SD-D2** (M×M) [proposed] P14 A band on the majority branch: the `vote_gate_majority` wire with
  `"abstain_band": [0.7, 0.9]` added to its gate gives the chip `_chip("gate · agreement &gt;= " +
  _N("0.6", "0.6") + " · band [" + _N("0.7", "0.7") + ", " + _N("0.9", "0.9") + "] · observed " +
  _AGREEMENT + " · majority")`.
- **SD-D3** (M×M) [proposed] P14 The run summary mean does not overflow: `_mean_cell([1e308,
  1e308])` is `"<td>" + _N("1e+308", "1e+308") + " <span class='sf-cmb__nn'>n=2</span></td>"`;
  `_mean_cell([1.0, 2.0])` keeps today's text (`1.5`).
- **SD-D4** (M×L) [proposed] A negative coefficient shows as written: an entry
  `{"source": "sum", "coefficients": {"a": 2.0, "b": -0.5}}` gives
  `source: sum of 2.0 × a + -0.5 × b`.

## 4. Non-functional requirements

- Every text is escaped (`html.escape`), as today. A name or a number never reaches the page raw.
  [existing]

## 5. Out of scope

- A new report-trace.v1 field (part 5 P16: the field set does not change).
- A chart of the sum values.

## 6. Open questions

None.

## 7. TDD plan

New test file: `ST/test_sum_band_display.py` (reads `COMBINE_CONTRACT / "evidence_cases.json"`
under `@requires_engine_app` and builds the Case by hand, as `ST/test_gate_display.py` does).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `existing_cases_render_the_same_bytes` (list L37 digests taken on base) | unit | SD-D1 | H×M | passes today |
| 2 | `sum_column_title_names_the_coefficients` | unit | SD-1 | M×M | `_source_text` |
| 3 | `run_summary_mean_header_names_the_sum` | unit | SD-2 | M×M | `_StepSummary.add` |
| 4 | `case_pane_shows_the_band_and_the_in_band_verdict` | unit | SD-3 | H×M | `_gate_chip`, `_gate_verdict` |
| 5 | `case_pane_shows_a_band_on_the_majority_branch` | unit | SD-D2 | M×M | — |
| 6 | `run_summary_counts_the_band` (both SD-4 lines) | unit | SD-4 | H×M | `_StepSummary.band`, `_gate_line` |
| 7 | `export_carries_the_band_and_in_band` | unit | SD-5 | M×M | none expected |
| 8 | `a_malformed_sum_entry_shows_source_sum` | unit | SD-E1 | M×L | `_source_text` |
| 9 | `run_summary_mean_does_not_overflow` | unit | SD-D3 | M×M | `_mean_cell` |
| 10 | `a_negative_coefficient_shows_as_written` | unit | SD-D4 | M×L | — |

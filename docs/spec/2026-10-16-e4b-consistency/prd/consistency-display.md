# PRD: Show consistency in the report (part 4 surfaces)

**Source:** epic ("The value is a number stored on that member's answer. The report shows it and
the source."), ans:Q4 ("the count of failed samples is recorded") · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §8](../erd.md) · contracts: C4 · uses: [consistency-record](consistency-record.md),
[consistency-value](consistency-value.md) (its contract cases)

## 1. Summary and user story

As a researcher who reads a run report, I want the Combine section of a Case to show each member's
consistency value, how many of its samples failed, and a step fact with the sample totals, and I
want the run summary to say how many samples failed over the run, so that I can see when a value
rests on fewer samples than I asked for.

## 2. Background and constraints

- Part 4 shows every recorded signal of a member as a column; the header title names the declared
  source (`_signal_head`, S/_ui/combine_view.py:240-250). So the consistency value and
  `source: consistency` already show with no change. [existing]
- A number shows 4 significant digits with the exact value as its title; a missing value is an em
  dash whose title is the reason (`number_html`, `dash_html`, `missing_reason`,
  S/_ui/combine_view.py:59-92; part 4 ans:Q3). [existing]
- The export writes `operations[].combine` as the evidence `to_dict()` (S/case_result.py:336), so
  the `consistency` record is in the export with no export change. The report-trace.v1 field set
  does not change. [existing]
- Every text from data goes through `html.escape` (S/_ui/combine_view.py:1-4 INVARIANT). [existing]

### 2.1 Current behavior

`_chips` (S/_ui/combine_view.py:179-197) has no sample chip; `_member_row` (:252-270) shows a
missing consistency value with the generic reason `no cons recorded`; `_StepSummary` (:317-358)
and `_summary_html` (:361-375) have no sample line.

**Delta.**

1. `_chips`: one new chip after the `mean` chip, only when `evidence.consistency` is set:
   `escape(f"samples · {name} · {n} per member · failed {F} of {T}")`, with `n` from
   `evidence.declared[name]["n"]`, `T = n * len(evidence.members)` and `F` the sum of `failed`.
2. `_member_row`: for the consistency name, the cell is
   `number_html(value, reason)` and then, when the member's `failed > 0`,
   ` <span class='sf-cmb__nn'>{failed} failed</span>`. The reason of a missing value:
   `missing_reason(row, name)` when the row is `fail` or `excluded`; else `"every sample failed"`
   when `succeeded == 0`; else `"no answer to compare"`.
3. `_StepSummary`: new counters `sample_name: str | None`, `samples_failed: int`,
   `samples_total: int`, filled from each Case's record; `_summary_html` writes, after the gate
   line, `<div class='sf-chips'><span class='sf-chip'>samples · {name} · failed {F} of
   {T}</span></div>` when the step has a record (escaped).

## 3. Scenarios and acceptance criteria

The cases are the three scenarios of `ET/data/combine_contract/consistency_evidence_cases.json`
(unit 2): `consistency_vote` (fixture V: n 4; failed 0, 2, 4), `consistency_pick_default_match`
(fixture W: n 3; failed 0, 0, 0), `consistency_no_votes` (CV-D5: n 4; every member `fail` /
`missing`; failed 0, 2, 4).

### 3.1 Happy path

- **CD-1** Given `consistency_vote`, then the Combine section has the chip
  `samples · cons · 4 per member · failed 6 of 12`. [proposed] P15
- **CD-2** Given `consistency_vote`, then the `cons` cell of member_1 is
  `<span class='sf-cmb__n' title='0.5'>0.5</span>`; of member_2 is
  `<span class='sf-cmb__n' title='1.0'>1</span> <span class='sf-cmb__nn'>2 failed</span>`; of
  member_3 is `<span class='sf-cmb__na' title='every sample failed'>—</span> <span
  class='sf-cmb__nn'>4 failed</span>`; and the `cons` header title is `source: consistency`.
  [stated ans:Q4]
- **CD-3** Given a Candidate with two Cases whose `op_synthesis_1` evidence is
  `consistency_vote`, then the run summary of that step holds `samples · cons · failed 12 of 24`
  directly after the heading (the step has no gate line), and the `cons mean` cells are 0.5 (n=2), 1
  (n=2) and a dash (n=0). [proposed] P15
- **CD-4** Given `consistency_vote`, then the JSON export of the Case holds
  `operations[0].combine.consistency` equal to the record of the fixture, byte for byte after
  `json.dumps`. [existing export]

### 3.2 Error paths

- **CD-E1** Given a Candidate with two Cases, one whose `op_synthesis_1` evidence is
  `consistency_vote` and one whose `op_synthesis_1` has no combine evidence (the part 4 P19 rule),
  then the run summary counts only the Case with evidence: `samples · cons · failed 6 of 12`.
  [existing part 4 P19]; [proposed] P15

### 3.3 Derived scenarios (risk-ordered)

- **CD-D1** (H×M) [implied] No section of the 37 cases of list L37 shows a `samples · ` chip or a
  `failed</span>` note, and their sections are unchanged (the part 4 and part 5 display tests
  stay green with no edit).
- **CD-D2** (M×M) [proposed] Given `consistency_pick_default_match`, the chip is
  `samples · cons · 3 per member · failed 0 of 9`, and no cell has a `failed` note.
- **CD-D3** (M×M) [proposed] Given `consistency_no_votes`, the member_2 cell is
  `<span class='sf-cmb__na' title='member failed: missing'>—</span> <span
  class='sf-cmb__nn'>2 failed</span>` (the member reason wins over the sample reason).
- **CD-D4** (M×L) [proposed] Given fixture V with member_1 text `"so twelve"` (no match value;
  member status not `fail`), the member_1 cell reason is `no answer to compare`. (A hand-built
  `CombineEvidence` in the SDK test, matched None, succeeded 4, failed 0.)
- **CD-D5** (M×L) [existing] The trace entries of `consistency_vote` have the report-trace.v1
  field sets (the frozen fields of `ST/test_frozen_record_fields.py`).

## 4. Non-functional requirements

- No new CSS class: the note reuses `sf-cmb__nn`. [proposed]

## 5. Out of scope

- A per-sample table (the sample texts are in the Case operations, not in the evidence).

## 6. Open questions

None.

## 7. TDD plan

New test file: `ST/test_consistency_display.py`. It reads
`COMBINE_CONTRACT / "consistency_evidence_cases.json"` under `@requires_engine_app` and builds the
Case by hand (the `ST/test_member_exclusion.py:_case` pattern; never
`_answer_fixtures.fixture_case`).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `existing_sections_show_no_sample_facts` (the fixed list L37 of `evidence_cases.json`: no `samples · ` chip and no `failed</span>` in any section) | unit | CD-D1 | H×M | passes today |
| 2 | `the_step_chip_counts_the_failed_samples` | unit | CD-1, CD-D2 | H×M | `_chips` |
| 3 | `each_member_cell_shows_its_value_and_its_failed_samples` | unit | CD-2 | H×M | `_member_row` |
| 4 | `a_missing_value_names_why` | unit | CD-D3, CD-D4 | M×M | reason order |
| 5 | `the_run_summary_sums_the_failed_samples` and `a_case_without_evidence_is_not_counted` | unit | CD-3, CD-E1 | M×M | `_StepSummary`, `_summary_html` |
| 6 | `the_export_holds_the_consistency_record` | unit | CD-4 | M×M | — (expected green at GREEN of unit 1; if green at RED, the ledger records it as a CHAR row) |
| 7 | `the_trace_field_sets_do_not_change` | unit | CD-D5 | M×L | — (CHAR-like guard) |

Pinned edits of this PRD: none.

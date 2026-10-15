# PRD: The Case trace in the JSON export (`trace` per Case)

**Source:** ans:Q1 ("Trace in the JSON export") · **Priority:** P0
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2–3](../erd.md) · contract: [C1](../contracts.md#c1-report-export--sdk--json-file-string-or-download-link-sync)

## 1. Summary and user story

As a researcher who shares or archives `report.json`, I want each Case with a combine step to
carry its trace, so that a reader of the file sees which operation was which member, what each
member gave, and how the step decided, without the SDK and without the live report object.

## 2. Background and constraints

- The owner chose the export as a surface and accepted that it "Makes exports larger; changes the
  export format." [stated ans:Q1]
- [proposed] P1: the additive edit of report.v1 is a new decision, by analogy with part 1 ans:Q5
  ("additive edit, no need to care abour versions for now",
  docs/spec/2026-10-13-e4b-combine-extensions/00-overview.md:86). That answer was about
  `combine-spec.v1` (part 1 D5, a new reducer kind), not about report.v1. The owner approves it
  with plan §6 action 1.

### 2.1 Current behavior

- The export is JSON only. Each Case object is `case.to_dict()`: `CandidateResult.to_dict()` builds
  `[case.to_dict() for case in self.cases]`, and the streaming `iter_report_json` builds
  `(case.to_dict() for case in candidate.cases)`. [existing S/report.py:483-484]
  [existing S/_report_export.py:16-21]
- The combine evidence is already in the export, in `operations[].combine`.
  [existing S/case_result.py:323-335]
- The trace is a derived view: `case.trace()` and `report.trace_dict()`
  (`screamingface.report-trace.v1`). It is not in the export. `_candidate_trace` builds it with
  the Candidate's own graph. [existing S/case_result.py:572-578] [existing S/report.py:643-649,966-979]
- `CaseResult.to_dict()` mirrors the Engine wire. The strict decoder `_case_result` accepts only
  the known Case keys (required set plus `operations`, `attempts`, `abstained`).
  [existing S/_evaluation/results.py:360-383]
- Two byte goldens pin the export of Cases with combine evidence:
  `ST/data/report_v1_combine_report.json` (Case 3, `op_opus_aggregate`) and
  `ST/data/report_v1_vote_median_report.json` (Case 1 of `vote` and of `median`,
  `op_synthesis_1`). `ST/test_e4b_schema_pins.py:28-33` pins their SHA-256.
  [existing ST/test_report_v1_identity.py:89-93] [existing ST/test_report_v1_vote_identity.py:73-81]

**Delta.** One private generator on `CandidateResult` builds each exported Case object. It is
`case.to_dict()`, plus a last key `trace` when the Case has combine evidence. Both export paths use
it. `CaseResult.to_dict()` does not change. [proposed] P1, P2

```python
# S/report.py, class CandidateResult
def to_dict(self) -> dict[str, object]:
    return self._export_fields(cases=list(self._export_cases()))

def _export_cases(self) -> Iterator[dict[str, object]]:
    """Each Case as report.v1 exports it: ``case.to_dict()``, then ``trace`` (E4b part 4, P1).

    WHY not in CaseResult.to_dict: that dict mirrors the Engine wire, and the strict decoder
    refuses an unknown key. WHY the Candidate graph: the same rule as ``trace_dict``.
    """
    graph = {operation.id: operation for operation in self.operations}
    for case in self.cases:
        selected = case.to_dict()
        if case.operations is not None and any(
            operation.combine is not None for operation in case.operations
        ):
            selected["trace"] = _case_entries(case, graph)
        yield selected
```

```python
# S/report.py, module level, next to _candidate_trace
def _case_entries(
    case: CaseResult, graph: Mapping[str, OperationInfo]
) -> list[dict[str, object]]:
    """One Case's report-trace.v1 entries: the one builder for trace_dict() and the export (EC-I2)."""
    return [entry.to_dict() for entry in case_trace(case, graph)]
```

`_candidate_trace` uses it: `"entries": _case_entries(case, graph)` (P20). Its output does not
change.

```python
# S/_report_export.py, iter_report_json
candidates = (
    candidate._export_fields(cases=candidate._export_cases()) for candidate in report.candidates
)
```

The docstring of `Report.trace_dict` changes from "(derived; not report.v1)" to "(derived; the
export also holds each Case's entries as its `trace` key, E4b part 4)". Do not change
`CaseResult.trace` or `CaseResult.to_dict`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **XT-1** Given a Candidate with the graph `fixture_graph(4)` and Case 1 =
  `fixture_case("vote_one_failed", case_id=1)`, then the exported Case 1 has a last key `trace`
  whose entries have the kinds `model_call` ×3, `extract` ×3, `reduce`; the `model_call` member ids
  are `member_1`, `member_2`, `member_3`; the `reduce` entry has `op: "vote"`, `mode: "select"`,
  `chosen: ["member_1"]`, `dropped: 1`, `judge_operation_id: null`, `judge_model: null`, and
  `tally: [{"value": "42", "score": 2.0, "holders": ["member_1", "member_3"]}]`. [stated ans:Q1]
- **XT-2** Given the same report, then `json.loads(report.to_json())` equals `report.to_dict()`, and
  the file that `report.export(path)` writes equals `report.to_json()`. [existing S/report.py:636-641]
- **XT-3** Given an abstained Case with combine evidence (`abstained=True`), then the last two keys
  of its exported object are `abstained`, `trace`. [proposed] P1

### 3.2 Error paths

- **XT-E1** Given a Case with no operations, a Case whose operations have no combine evidence, or a
  failed Case, then the exported object equals `case.to_dict()` and has no `trace`. [proposed] P1
- **XT-E2** Given a Case with Attempts whose operations hold combine evidence, and `operations` of
  the Case itself is None, then the exported object has no `trace`. [proposed] P15

### 3.3 Derived scenarios (risk-ordered)

- **XT-D1** (H×M) [proposed] Given every Case of both golden reports, then the exported object
  minus `trace` equals `case.to_dict()` (EC-I1), and only the Cases with combine evidence have
  `trace`.
- **XT-D2** (H×M) [implied] Given member outputs that contain the text `SENTINEL`, then the exported
  `trace` does not contain `SENTINEL` (EC-I3). Fixture limit: the step uses `last_number@1`, so the
  extracted `raw` and `value` are a number. This row does not cover `whole@1` or `json_object@1`,
  whose `extract` entries repeat the whole reply (N1).
- **XT-D3** (M×M) [proposed] Given any exported `trace` entry, then its keys are exactly
  `["kind", *TRACE_FIELDS[kind]]`, in that order. The report-trace.v1 snapshot does not change.
- **XT-D4** (M×M) [proposed] Given the vote and median report, then each exported `trace` equals the
  `entries` of the same Case in `report.trace_dict()` (EC-I2).
- **XT-D5** (M×L) [existing] Given any report, then `case.to_dict()` never has `trace` (EC-I4).
- **XT-D6** (M×L) [proposed] Given any report, then `report.to_dict()["schema"]` is still
  `"screamingface.report.v1"` (EC-I5).

## 4. Non-functional requirements

- The streaming export stays streaming: `_export_cases` is a generator, and each Case object is
  built when it is written. [existing S/_report_export.py:26-41]
- Size: one entry per non-combine operation, one per member of each combine step, one per step. No
  new cap (P3). The text of `extract` entries is bounded by the Engine reading caps. N1 applies.
- Deterministic: the same report gives the same bytes. [existing S/_case_views.py:1-4]

## 5. Out of scope

- A new schema id (`report.v2`) or a JSON Schema file for report.v1. [proposed]
- A trace for Attempt operations (D1).
- An opt-in flag on `export()` (a public API change; ans:Q1 asks for the trace in the export).

## 6. Open questions

None.

## 7. TDD plan

Test file: `ST/test_export_trace.py` (new). Build the report as `ST/test_report_trace.py:114-139`
(`_candidate`) does: copy that helper into the new file and give it `operations` and `cases`
parameters. Build the abstained Case with `output=""`, `grade` score `0.0` (the abstained rule,
S/case_result.py:695-700) and an `op_synthesis_1` operation with `combine=evidence_cases()["vote_abstain"]`.
Build the Attempts Case as `ST/test_case_attempts.py:59-68` does.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `case_to_dict_of_a_combine_case_has_no_trace_key` | unit | [existing S/case_result.py:580-604] | M×L | passes today and after (XT-D5) |
| 2 | CHAR `json_export_equals_to_dict_for_a_combine_report` | unit | XT-2 | H×L | passes today and after |
| 3 | CHAR `case_without_combine_evidence_exports_its_to_dict` | unit | XT-E1 | H×M | passes today and after |
| 4 | `combine_case_export_carries_its_trace` | unit | XT-1 | H×M | `_export_cases` |
| 5 | `trace_is_the_last_key_after_abstained` | unit | XT-3 | M×M | key added last |
| 6 | `to_json_export_file_and_to_dict_carry_the_same_trace` | unit | XT-2 | H×L | `iter_report_json` uses `_export_cases` |
| 7 | `case_without_operations_or_combine_or_failed_has_no_trace` | unit | XT-E1 | H×M | the `any(...)` guard |
| 8 | `case_with_attempts_has_no_trace_key` | unit | XT-E2 | M×L | guard reads `case.operations` only |
| 9 | `exported_trace_holds_no_member_output_text` | unit | XT-D2 | H×M | copy the SENTINEL pattern of `ST/test_report_trace.py:324-350` |
| 10 | `exported_entries_keep_the_report_trace_v1_field_sets` | unit | XT-D3 | M×M | reuses `TraceEntry.to_dict()` |
| 11 | `export_minus_trace_is_case_to_dict_for_every_golden_case` | unit | XT-D1, XT-D6 | H×M | uses `combine_report()` (`ST/test_report_v1_identity.py`) and `vote_median_report()` (`ST/test_report_v1_vote_identity.py`) |
| 12 | PIN `report_v1_goldens_hold_the_trace` | golden | XT-1, P4 | H×H | regenerate the two goldens, then update the two SHA-256 values in `ST/test_e4b_schema_pins.py` (lines 29 and 33); the existing identity tests then pass |
| 13 | `exported_trace_equals_trace_dict_entries` | unit | XT-D4 | M×M | one builder, `_case_entries` (P20) |

Row 12 commands (from `packages/screamingface`):

```bash
uv run python -c "import sys; sys.path.insert(0,'tests'); import test_report_v1_vote_identity as m; m.write_golden()"
uv run python -c "import sys; sys.path.insert(0,'tests'); import test_report_v1_identity as m; m.COMBINE_GOLDEN.write_text(m.combine_report().to_json() + '\n', encoding='utf-8')"
shasum -a 256 tests/data/report_v1_combine_report.json tests/data/report_v1_vote_median_report.json
```

Check the golden diff before the commit: the only change in each file is `,"trace":[...]` at the
end of each Case that has combine evidence (row 11 proves it).

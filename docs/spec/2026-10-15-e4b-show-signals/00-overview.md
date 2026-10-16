# E4b part 4: show signals — overview

**Status:** built (2026-10-15); the owner approved P1, P15 and the three unit 1 pinned edits on 2026-10-15. **Epic:** E4b (OME-1290). **Leaf:** filed at
PR-open.
**Base:** branch `e4b-signal-sources` (E4b part 3, restacked on part 2 `e4b-evidence-completeness`)
at `9f42391eb`. Part 4 reads the values that parts 2 and 3 write.

## 1. Summary

Parts 2 and 3 write each member's status, reason, weight, score, rank, the cut, the judge link and
the declared signals into the combine evidence and the trace. A researcher can read them only from
Python (`case.answers()`, `case.trace()`, `report.trace_dict()`). The HTML report does not show
them, and the JSON export does not hold the trace. Epic OME-1290 asks to "save signals and show them
in the Client/report" (K3) and that "the report shows the value and its source" (A3, display half).
This part adds three surfaces (ans:Q1):

- a **Combine section** in the Case pane of the HTML report: one per reducer step of the Case, with
  the step facts (reducer, rule, result, cut, signal read, judge model, agreement, tie, dropped)
  and one row per member (status, value, weight, score, rank, every recorded signal, chosen);
- a **run summary** in each Candidate card: for each reducer step, how often each member was
  chosen and excluded, and the mean of each declared signal with its count `n`;
- the **Case trace in the JSON export**: each exported Case that has a combine step gets a new
  key `trace` with its `screamingface.report-trace.v1` entries.

The Combine section is shown for every reducer step, a plain majority vote included (ans:Q2).
Numbers show 4 significant digits; the exact stored value is the hover title; a missing value is an
em dash with its reason in the title (ans:Q3).

SDK only. No Engine change, no wire change, no new schema id, no new public Python API (ans:Q1),
and no url4 change.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `ET/` = `apps/screamingface-engine/tests/unit/`,
`ST/` = `packages/screamingface/tests/`. Line numbers are on base `9f42391eb`.

**Epic map** (OME-1290 items that this part closes):

| Epic item | Status after this part |
|---|---|
| K3 save signals and show them in the Client/report | done: [case-pane](prd/case-pane.md), [run-summary](prd/run-summary.md), [export-trace](prd/export-trace.md) |
| A3 the report shows the value and its source (display half) | done: declared signal columns name their source ([case-pane](prd/case-pane.md) CP-4) |
| Part 2 D1 display of `"excluded"`, `rank`, `cut`, the judge link | done ([case-pane](prd/case-pane.md)) |
| Part 3 D2 display of signals in the report | done ([case-pane](prd/case-pane.md), [run-summary](prd/run-summary.md)) |

## 2. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| SDK report export (`S/report.py`, `S/_report_export.py`) | report.v1 JSON | export-trace |
| SDK report HTML (`S/_ui/report_view.py`, new `S/_ui/combine_view.py`) | Case pane, Candidate card, style | display-format, case-pane, run-summary |
| SDK views (`S/_case_views.py`) | the trace (read only, no change) | — |
| Test data (`ST/data/report_v1_*.json`, `ST/test_e4b_schema_pins.py`) | report.v1 byte goldens | export-trace (owner-approved edits) |
| Docs (`packages/screamingface/README.md`, `packages/screamingface/CHANGELOG.md`) | user guidance | docs |

## 3. Reading order

1. [erd.md](erd.md)
2. [prd/display-format.md](prd/display-format.md) (component, used by all display PRDs)
3. [prd/export-trace.md](prd/export-trace.md) (P0)
4. [prd/case-pane.md](prd/case-pane.md) (P0)
5. [prd/run-summary.md](prd/run-summary.md) (P1)
6. [prd/docs.md](prd/docs.md) (P2)
7. [contracts.md](contracts.md), [test-plan.md](test-plan.md)

## 4. PRD index

| PRD | Lifecycle | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|---|
| [export-trace](prd/export-trace.md) | existing | 3 / 2 / 6 | 13 |
| [display-format](prd/display-format.md) | planned | 3 / 2 / 4 | 11 |
| [case-pane](prd/case-pane.md) | existing | 5 / 4 / 7 | 18 |
| [run-summary](prd/run-summary.md) | existing | 3 / 2 / 5 | 11 |
| [docs](prd/docs.md) | existing | 2 / 0 / 2 | 5 |
| **Total** | | **16 / 10 / 24** | **58** |

## 5. Interview ledger

The prompt is the E4b roadmap ("Part 4. Show signals") and the owner brief of 2026-10-15. The
owner answered three questions (multiple choice). The answers are verbatim.

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | Which surfaces show the combine data? (multiSelect) | "Case pane table (Recommended)", "Run-level summary", "Trace in the JSON export" | NOT selected: "Python accessor" (`case.combine_rows()`). No new public Python API. The owner saw that the export option "Makes exports larger; changes the export format." |
| Q2 | When does the Case pane show the Combine section? | "Every reducer step" | **against the recommendation** ("Only with signal data"). A plain majority vote also shows its section (values, tally). |
| Q3 | How are numbers shown? | "Short + exact on hover (Recommended)" | 4 significant digits; the exact stored value in a title tooltip; a missing value is an em dash with its reason (the existing report convention). |

Option texts the owner saw (they set the scope):

- Case pane table: "a 'Combine' section in the HTML report's Case detail pane (_pane_html): one row
  per member, plus the step facts (cut, judge model, agreement, tie)."
- Run-level summary: "per candidate in the report card: how often each member was excluded or
  chosen, and the mean of each declared signal."
- Trace in the JSON export: "add the combine trace to the exported report JSON. Makes exports
  larger; changes the export format."

## 6. Global decisions [proposed]

| # | Decision | Where |
|---|---|---|
| P1 | The export key is `trace`. It holds the whole Case trace (`model_call`, `extract` and `reduce` entries of `screamingface.report-trace.v1`), not only the combine entries, because the `model_call` entries name which operation is which member, and report.v1 does not have that link today. The key is on a Case only when at least one of its `operations` has combine evidence. It is the last key of the Case object. The schema id stays `screamingface.report.v1` (additive edit). This is a new decision for report.v1, by analogy with part 1 ans:Q5. That answer was about `combine-spec.v1` (part 1 D5), not about report.v1, so the owner approves it here (plan §6 action 1). **Owner approved 2026-10-15: same id, additive.** | [export-trace](prd/export-trace.md) §2 |
| P2 | The export adds the key at the report level (`CandidateResult._export_cases`), with the Candidate's own operation graph, as `report.trace_dict()` does. `CaseResult.to_dict()` does not change: it mirrors the Engine wire, and the strict decoder `_case_result` (S/_evaluation/results.py:360-383) refuses an unknown key. | [export-trace](prd/export-trace.md) §2.1 |
| P3 | No new size cap. The trace of one Case has one entry per non-combine operation, one per member of each combine step, and one per combine step. It copies no member output text except each member's extracted `raw` and `value` in the `extract` entries. For `whole@1` and `json_object@1` these are the whole reply (N1). The Engine already bounds them. | [export-trace](prd/export-trace.md) §4, N1 |
| P4 | The two report.v1 byte goldens and their two SHA-256 pins change. This is unavoidable under ans:Q1: both goldens hold a Case with combine evidence. Each is an owner-approved pinned edit. | [export-trace](prd/export-trace.md) XT#12 |
| P5 | A float shows `format(value, ".4g")` (trailing zeros dropped, the `:g` precedent of `_score_text`); its title is `repr(value)`, the shortest text that gives back the exact stored float. An integer (rank, `k`, a count) shows as it is, with no title. | [display-format](prd/display-format.md) |
| P6 | A missing value gets one reason, by rule MR-1..MR-3: a failed member, then an excluded member, then "no <label> recorded". The title of the em dash is the reason. | [display-format](prd/display-format.md) §2 |
| P7 | A member value cell shows at most 80 characters, then "…". It has no title. The full value is in the JSON export and in `case.answers()`. | [display-format](prd/display-format.md) DF-3 |
| P8 | Every text that comes from data (member id, member value, tally value, operation label, judge model, reasons, signal keys, declared names and sources) goes through `html.escape(..., quote=True)`, in the cell and header text and in each attribute. Attribute values are in single quotes (house style). No data is ever put into the page as raw HTML. | [display-format](prd/display-format.md), [case-pane](prd/case-pane.md) CP-E3 |
| P9 | The Combine style rules (prefix `.sf-cmb`) are one module constant `STYLE = "<style>…</style>"` in `S/_ui/combine_view.py`, joined into `_STYLE` after `ACCOUNTING_STYLE` (the house precedent, S/_ui/report_view.py:34-37). Theme variables only. They use no token that an existing test forbids in the report HTML (DF#10). The cells are left-aligned and the rows have no host zebra background, as `.sf-eval__table` does (S/_ui/evaluation_view.py:41,47). The header cells have `scope='col'`, as the eval table (S/_ui/evaluation_view.py:226). The Case pane itself adds no `<style>` tag. | [display-format](prd/display-format.md) DF-D3 |
| P10 | The Combine section is in the "Answer & grading" view of the pane, after the failures and before the criteria. One section per combine step of the Case (P19), in operation order. The heading uses the operation label of the Candidate graph. | [case-pane](prd/case-pane.md) §2 |
| P11 | The `value`, `status` and `chosen` columns are always shown. The `weight`, `score` and `rank` columns are shown only when at least one member row of that step has a value. Each recorded signal key has its own column, also when every value is None. | [case-pane](prd/case-pane.md) §2 |
| P12 | The judge chip reads the trace `reduce` entry of the step (`judge_operation_id`, `judge_model`, part 2 P8), so the view and the trace use one rule. The pane builds the trace with the Candidate graph, as the export does. | [case-pane](prd/case-pane.md) CP-3 |
| P13 | The run summary groups the evidence by the combine `operation_id`. "chosen" = the member id is in `evidence.chosen` for that Case. "excluded" = the member row has `status == "excluded"`. Both show as `{count} of {N}`, so the two columns read the same way. The mean of a declared signal = `math.fsum` of the member's non-None values over the step's Cases, divided by their count `n`; every row status counts. Member rows and steps are in first-seen order. One pass over the Cases. The block is absent when no Case has combine evidence. | [run-summary](prd/run-summary.md) |
| P14 | The run summary shows the declared signals only (the epic word). The E4a keys (`cost_usd`, `field:<path>`, `score:judge`, …) show per Case in the Combine section. | [run-summary](prd/run-summary.md) §5 |
| P15 | **Exception to ans:Q2 (the owner approves it, plan §6 action 1).** The combine steps of an Attempt (`case.attempts[i].operations`) are not shown and not exported in this part, as `case.trace()` does not trace them today. No Benchmark declares more than one Attempt today, so the risk is low. **Owner approved 2026-10-15: accept; follow-up when a reducer Benchmark declares Attempts.** | D1 |
| P16 | The `median` and `mean` evidence keys are text (the answer itself). The section shows them as stored text, not as a rounded number. | [case-pane](prd/case-pane.md) CP-D5 |
| P17 | All new code is private: the new module `S/_ui/combine_view.py` has `__all__ = []`, and the new report method is `_export_cases`. The public surface snapshot `ST/public_surface_snapshot.json` does not change (ans:Q1). | [display-format](prd/display-format.md) DF#11 |
| P18 | No existing HTML test, snapshot or golden changes because of ans:Q2. Checked on `9f42391eb`: no report-HTML test renders a Case with combine evidence (24 HTML test files; `ST/test_case_abstained.py` uses `abstained=True` without operations; `ST/test_reducer_slot.py:122-123` renders the Fusion repr, not a report). Checked again on `b556d25c7` for P19: no report-HTML test renders a Candidate graph with a `kind == "combine"` node. The only test files with such a node are `ST/_answer_fixtures.py`, `ST/test_answers.py`, `ST/test_judge_reducer.py`, `ST/test_merge_writer_compile.py`, `ST/test_reducer_slot.py` and `ST/data/report_v1_vote_median_report.json`; none of them renders the report HTML. The node `op_opus_aggregate` of `ST/data/report_v1_combine_report.json` has kind `aggregation`. The section is emitted only for a Case with a combine step. | [case-pane](prd/case-pane.md) CP#1 |
| P19 | A combine step with no evidence also gets a section (ans:Q2 "Every reducer step"). The step is a Case operation with `combine is None` whose node in the Candidate graph has `kind == "combine"`: a pre-E4a Engine (S/_case_views.py:128-130), or the Engine's ambiguous-fingerprint branch, which never writes evidence (E/benchmarks/operation_outputs.py:150-157). The short section has the heading `combine · {label}` and one chip `evidence · —`, with the title `no combine evidence recorded for this step`. So the reader can tell "no reducer" from "a reducer with no record". The run summary and the export do not change for such a step. | [case-pane](prd/case-pane.md) CP-E4 |
| P20 | One builder for each repeated output. `S/_ui/combine_view.py` has `_label(graph, operation_id)` and `_table(head, rows)`, used by the Case pane and the run summary. `S/report.py` has `_case_entries(case, graph)`, used by `_candidate_trace` (`trace_dict()`) and `_export_cases`, so EC-I2 holds by construction. | [case-pane](prd/case-pane.md) §2, [export-trace](prd/export-trace.md) §2.1 |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | Combine steps inside Attempts (pane, summary, export) | not planned; revisit when a reducer Benchmark declares Attempts |
| D2 | The merge `fields` readings and the raw judge reply in the pane | not planned; both are in the JSON export (`operations[].combine`) |
| D3 | Member display names (`member_1` → the model name) in the section and the summary | not planned; the `model_call` trace entries in the export give the link. **Known confusion:** the run summary sits directly below the card's members block, which names the models (for example `opus`), but the summary rows say `member_1`, `member_2`, with no link in the card. A cheap fix exists: a `title` on each member cell with the escaped label of the producer operation (`graph[node.depends_on[k-1]].label`, the `_member_ids` rule, S/_case_views.py:260-272). The owner can ask for it (plan §6 action 1). |
| D4 | A public accessor (`case.combine_rows()`), a DataFrame, scoreboard or studio display | not planned (ans:Q1) |
| D5 | Several signals in one step, coefficients, abstain band | part 6 |

Scope notes:

- **N1** For a step that uses `whole@1` or `json_object@1`, `raw` and `value` are the whole reply.
  The exported `extract` entries repeat them, so that text is in the export twice (once in
  `operations[].combine`, once in `trace`). The owner accepted larger exports (ans:Q1). EC-I3 and the README say this.
- **N2** A larger export passes the 64 KiB limit of the inline download link more often. Then the
  report shows the existing text "Full export: `report.export('report.json')`"
  (S/_ui/report_view.py:281-283). No change to that rule.
- **N3** A static preview pane over 24,000 bytes falls back to the short preview
  (S/_ui/report_view.py:798-807). A large Combine section makes this happen sooner. The live
  browser renders the full pane, with the section.
- **N4** The run summary reads every Case of the Candidate once more, as `abstained_count` already
  does for the card (S/report.py:465-468).
- **N5** The docstrings of `ST/test_report_v1_identity.py` and `ST/test_e4b_schema_pins.py` say
  that E4b does not change report.v1. After part 4 they are out of date. This part does not edit
  them (smallest pinned edit). The owner can approve a docstring edit later.

## 8. What changes for related work

- **E4b parts 2 and 3** are the base. If either changes before merge, rebase this branch onto the
  new part 3 tip.
- **E4b part 5 (gates)** can show its gate record in the same Combine section.
- **E4b part 6** (several signals in one step) adds columns; the column rule P11 already covers
  any number of signal keys.

## 9. Build errata

- **E1 (CP-E3, CP#12).** A declared NAME must be a signal name (`S/combine_evidence.py` `_declared_map`),
  so the decoder refuses the declared name `<b>k</b>`. The test puts the two hostile strings on two
  columns: the plain signal key `<b>k</b>` (header `<th scope='col'>&lt;b&gt;k&lt;/b&gt;</th>`, no
  title) and the declared name `conf` with the source `<x>` (header
  `<th scope='col' title='source: &lt;x&gt;'>conf</th>`). The P8 coverage is the same. (ledger unit 3 D-1)
- **E2 (CP-D4, CP#8).** The tally table of `vote_one_failed` has its own `score` header. The pane has
  exactly one `<th scope='col'>score</th>` (the tally), and no `weight` or `rank` header. (ledger unit 3 D-2)
- **E3 (CP-D6, CP#16).** `case.to_dict()` of the 256-member Case is about 65,000 characters, not about
  51,000. The oracle (more than 32,000) holds. (ledger unit 3 D-3)
- **E4 (run summary).** The spec name `_member_row` collides with the unit 3 helper of the same name in
  `S/_ui/combine_view.py`. The run-summary helper is `_summary_row`. (ledger unit 4 D-5)

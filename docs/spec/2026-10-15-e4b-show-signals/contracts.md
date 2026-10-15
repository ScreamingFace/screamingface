# Contracts: E4b part 4 — show signals

One section per connection that part 4 changes. These connections do not change and keep their
contracts: the combine spec and the url4, the combine evidence (`screamingface.combine-evidence.v1`),
the Engine results wire and its SDK decoder (`_case_result`), `answer.v1`, and
`screamingface.report-trace.v1`. See `docs/spec/2026-10-15-e4b-evidence-completeness/contracts.md`
and `docs/spec/2026-10-15-e4b-signal-sources/contracts.md`.

## C1 Report export — SDK → JSON file, string or download link, sync

- **Shape.** `screamingface.report.v1`. Each Case object of `candidates[].cases` is
  `case.to_dict()`, plus, when the Case has combine evidence, a last key `trace`:
  ```json
  {"status": "scored", "case_id": 1, "...": "...",
   "operations": [ {"operation_id": "op_model_1", "...": "..."},
                   {"operation_id": "op_synthesis_1", "...": "...", "combine": {"...": "..."}} ],
   "trace": [
     {"kind": "model_call", "operation_id": "op_model_1", "member_id": "member_1", "...": "..."},
     {"kind": "extract", "operation_id": "op_synthesis_1", "member_id": "member_1", "...": "..."},
     {"kind": "reduce", "operation_id": "op_synthesis_1", "op": "vote", "...": "...",
      "judge_operation_id": null, "judge_model": null}]}
  ```
  [stated ans:Q1] [proposed] P1
- **Policies.** The report root `schema` stays `screamingface.report.v1` (additive edit, part 1
  ans:Q5). The key order of the Case object is `case.to_dict()` order, then `trace`. The two export
  paths (`to_dict()` and the streaming `iter_report_json`) build the Case object with one private
  function, so they never differ. The entries use the Candidate's own graph (as `trace_dict()`).
  [existing S/report.py:966-979] [proposed] P2
- **Failure behavior.** A Case that cannot build its trace is a bug: `TraceEntry` raises on an
  unknown kind or field set, as today. The export does not catch it. [existing S/report_trace.py:72-87]
- **Contract tests.** XT#1–13. The byte goldens `ST/data/report_v1_combine_report.json` and
  `ST/data/report_v1_vote_median_report.json` pin the bytes (pinned edit, XT#12).

## C2 Case pane — SDK → notebook HTML (static report and live browser), in process

- **Shape.** `_pane_html(candidate, case, cost_html)` puts zero or more Combine sections into the
  "Answer & grading" view, after the failures and before the criteria. Each section is:
  ```html
  <div class='sf-cmb'><div class='sf-detail__k' title='op_synthesis_1'>combine · synthesis</div>
  <div class='sf-chips'><span class='sf-chip'>reducer · vote</span>…</div>
  <table class='sf-cmb__t'><thead><tr><th>member</th>…</tr></thead><tbody>…</tbody></table>
  [<table class='sf-cmb__t'>… tally …</table>]</div>
  ```
  [stated ans:Q1, ans:Q2] [proposed] P10, P11
- **Policies.** Numbers, missing values and text follow [display-format](prd/display-format.md). All
  data text is escaped. The style rules are in `_STYLE`; the pane adds no `<style>` tag. A Case
  without combine evidence renders as today. [stated ans:Q3] [proposed] P8, P9, P18
- **Failure behavior.** The view never raises for valid evidence. A judge link that the trace does
  not have gives no judge chip (or an em dash when only the model is missing). It never guesses.
  [existing S/_case_views.py:195-215]
- **Contract tests.** CP#1–17, DF#3–10.

## C3 Candidate card — SDK → notebook HTML, in process

- **Shape.** `_card_html(candidate, report, …)` puts one summary block after the members block and
  before the accounting note and the URL4 block:
  ```html
  <div class='sf-detail__k'>combine</div><div class='sf-cmb'>
  <div class='sf-cmb__h'>synthesis · vote · 3 cases</div>
  <table class='sf-cmb__t'><thead><tr><th>member</th><th>chosen</th><th>excluded</th>
  <th title='source: verbalized'>conf mean</th></tr></thead><tbody>…</tbody></table></div>
  ```
  [stated ans:Q1] [proposed] P13
- **Policies.** Absent when no Case has combine evidence. One pass over the Cases.
  [stated prompt] [proposed] P13
- **Failure behavior.** None new. An empty step cannot exist (a step exists only when a Case has its
  evidence).
- **Contract tests.** RS#1–11.

## C4 Layering and public surface — dependency

- `S/_ui/combine_view.py` imports only the standard library (`html`, `math`), `screamingface._case_views`
  (`case_trace`) and SDK record types (for type checking). `S/_ui/report_view.py` imports from it.
  No other module imports it. [proposed] P17
- `S/report.py` imports `case_trace` already (for `_candidate_trace`). The new private method
  `CandidateResult._export_cases` reuses it. [existing S/report.py:966-979]
- No new public name. `ST/public_surface_snapshot.json` keeps its bytes; `ST/test_public_surface.py`
  enforces it. [stated ans:Q1]
- No Engine module changes, so the Engine layering gate is not touched.

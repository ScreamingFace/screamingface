---
ticket: unfiled   # epic OME-1290 is the parent; the leaf is filed at PR-open
stack: screamingface, repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-15
finished:
---

# e4b-show-signals — E4b part 4, show signals

One ledger for the whole part. The plan is
[docs/plan/2026-10-15-e4b-show-signals.md](../plan/2026-10-15-e4b-show-signals.md). The spec is
[docs/spec/2026-10-15-e4b-show-signals/](../spec/2026-10-15-e4b-show-signals/00-overview.md).
Branch `e4b-show-signals`, base `9f42391eb` (part 3, restacked on part 2). Each unit gets its own
section below, in the order of plan §2.

## Spec

### Intent

Show the combine data of parts 2 and 3 to the user, in three places (ans:Q1): a Combine section
in the Case pane for every reducer step (ans:Q2), a run summary per reducer step in each Candidate
card, and the Case trace as a `trace` key in the JSON export. Numbers show 4 significant digits,
the exact value on hover, and a missing value is an em dash with its reason (ans:Q3). SDK only; no
public API, Engine, wire, url4 or schema id change.

### Owner decisions (verbatim)

- Q1 surfaces: "Case pane table (Recommended)", "Run-level summary", "Trace in the JSON export".
  Not selected: "Python accessor".
- Q2: "Every reducer step" (against the recommendation "Only with signal data").
- Q3: "Short + exact on hover (Recommended)".

### Spec files (commit `docs(e4b): spec and plan for E4b part 4 (show signals)`)

- `docs/spec/2026-10-15-e4b-show-signals/00-overview.md` (P1–P20, N1–N5, D1–D5)
- `docs/spec/2026-10-15-e4b-show-signals/erd.md`, `contracts.md`, `test-plan.md`
- `docs/spec/2026-10-15-e4b-show-signals/prd/`: `export-trace.md` (XT, 13 rows),
  `display-format.md` (DF, 11), `case-pane.md` (CP, 18), `run-summary.md` (RS, 11), `docs.md`
  (DC, 5). 58 rows.
- `docs/plan/2026-10-15-e4b-show-signals.md`

### Units

| # | Slug | PRD rows | Stacks | Pinned files |
|---|---|---|---|---|
| 1 | export-trace | XT#1–13 | screamingface, repo | `packages/screamingface/tests/data/report_v1_combine_report.json`, `packages/screamingface/tests/data/report_v1_vote_median_report.json`, `packages/screamingface/tests/test_e4b_schema_pins.py` (lines 29, 33) |
| 2 | display-format | DF#1–11 | screamingface, repo | none |
| 3 | case-pane | CP#1–18 | screamingface, repo | none |
| 4 | run-summary | RS#1–11 | screamingface, repo | none |
| 5 | docs | DC#1–5 | screamingface, repo | none |

### Facts checked on `9f42391eb` (intake, line numbers moved after the restack)

- No `.codegraph/` in this worktree; the facts were checked with grep and read.
- `case.answers()` S/case_result.py:563, `case.trace()` :572, `CaseResult.to_dict()` :580-604;
  `case_answers` S/_case_views.py:24, `case_trace` :105, `_combine_entries` :134, `_reduce_data`
  :157-171, `_judge_link` :195-215, `_signal_data` :218-223.
- `_pane_html` S/_ui/report_view.py:886; it does not render `to_dict()` JSON. `bounded_pane`
  (:798-807) only measures `case.to_dict()` (32,000 characters) and the pane (24,000 bytes).
- `abstained_count` S/report.py:465-468; `_abstained_text` S/_ui/report_view.py:332-334;
  `_card_html` :337-394; `_repr_html_` S/report.py:743-746.
- Export: `iter_report_json` S/_report_export.py:16-21; `CandidateResult.to_dict` S/report.py:483-484;
  `Report.trace_dict` :643-649; `_candidate_trace` :966-979. The combine evidence is already
  exported in `operations[].combine`; the trace is not.
- There is no JSON Schema file for report.v1. Two byte goldens pin it
  (`ST/data/report_v1_combine_report.json`, `ST/data/report_v1_vote_median_report.json`), and
  `ST/test_e4b_schema_pins.py:28-33` pins their SHA-256. Both hold Cases with combine evidence.
- `_case_result` (S/_evaluation/results.py:360-383) refuses unknown Case keys, so the `trace` key
  goes into the report export, not into `CaseResult.to_dict()`.
- No report-HTML test renders a Case with combine evidence, or a Candidate graph with a combine
  node (P18, checked again for P19 on `b556d25c7`). The e2e goldens
  (`ST/e2e/fixtures/goldens/*.golden.json`, golden-report.v1) hold no Case object and do not
  change. The lanes read exported Cases as dicts (`ST/e2e/fixtures/reducer_lane.py:444`,
  `ST/e2e/fixtures/report_tape.py:227`). The `format="inspect"` export does not use
  `case.to_dict()`.

### Spec review (2026-10-15)

A spec review gave 2 MAJOR and 14 MINOR findings. All are applied in the commit
`docs(e4b): review fixes for the E4b part 4 spec`. No owner answer changes.

- MAJOR, escaping: the signal-key header text, the pane member cell and the summary member cell
  now use `escape()`. CP-E3 / CP#12 also test a signal key `<b>k</b>` and a declared source `<x>`
  in the pane header (P8, CS-I4).
- MAJOR, ans:Q2: option (a). A Case operation with `combine is None` on a `kind == "combine"`
  graph node gets a short section (`evidence · —`), new P19, CP-E4, CP#18. The P18 check was run
  again: no report-HTML test renders a combine node. The Attempts exception (P15) is now explicit
  and goes to the owner (plan §6 action 1).
- EC-I3, P3 and the README sentence now say that the trace holds each member's extracted `raw`
  and `value` (the whole reply for `whole@1` and `json_object@1`). XT-D2 names its fixture limit.
- test-plan risk row: RS#11 → RS#7.
- erd §7: the e2e golden check is recorded; the wrong `reducer_golden.py` citation is replaced.
- RED stubs of `combine_sections_html` and `combine_summary_html` return `""` and are wired in
  GREEN (test-plan §2, case-pane §7, run-summary §7).
- Shared helpers named: `_label`, `_table` (combine_view) and `_case_entries` (S/report.py), P20.
- `text_html` keeps its own clip, with a WHY comment (import cycle with `report_view`).
- Style: one `STYLE = "<style>…</style>"` constant joined into `_STYLE` after `ACCOUNTING_STYLE`;
  `text-align:left` on `th` and `td`; `tbody tr{background:transparent!important}`; header cells
  `<th scope='col'>`, with all CP and RS header oracles updated.
- CP-D2 / RS-D2 get the exact graph and Case; CP-D6 gets the wire builder `_wide_vote_wire()` and
  the correct fallback reason (`case.to_dict()` over 32,000 characters).
- One rule for test helpers: import a helper used as it is (house precedent), copy it only to
  change it. docs §7 now imports `_section`.
- CHANGELOG: the bullet goes under the FIRST `### Features` of `## Unreleased` (line 17).
- P1: the report.v1 additive edit is a [proposed] new decision by analogy with part 1 ans:Q5.
- display-format citation `report_view.py:9` → `:10`.
- Run summary: `excluded` shows `{n} of {N}`, as `chosen` (RS-1, RS-3 oracles updated).
- D3 names the `member_k` versus model-name confusion for the owner; no member-cell title is
  built.

### Status

Spec written and reviewed. Build not started. The units append their sections (Intent, Planned changes, Pinned
edits, Test plan, Acceptance, Deviations, Outcome) below.

## Unit 1: the Case trace in the report.v1 export (`trace`)

### Intent

PRD `export-trace`, rows XT#1–13 (ans:Q1 "Trace in the JSON export"; P1–P4, P15, P20, N1). Each
exported Case with combine evidence in `case.operations` gets a last key `trace`: its
`screamingface.report-trace.v1` entries, built with the Candidate's own graph. Every other Case and
key keeps its bytes; `CaseResult.to_dict()` does not change; the schema id stays
`screamingface.report.v1`. One private builder, `_case_entries`, serves the export and
`trace_dict()` (EC-I2 by construction). No public name, no Engine, wire or url4 change.

### Planned changes

- `S/report.py`: `CandidateResult._export_cases` (new private generator), `CandidateResult.to_dict`
  uses it, module-level `_case_entries` (new), `_candidate_trace` uses it, the `Report.trace_dict`
  docstring.
- `S/_report_export.py`: `iter_report_json` uses `candidate._export_cases()`.
- New test file: `ST/test_export_trace.py` (13 tests).

### Pinned edits

- `packages/screamingface/tests/data/report_v1_combine_report.json`: regenerated; `,"trace":[...]`
  at the end of Case 3 only.
- `packages/screamingface/tests/data/report_v1_vote_median_report.json`: regenerated with
  `write_golden()`; `,"trace":[...]` at the end of Case 1 of `vote` and of `median` only.
- `packages/screamingface/tests/test_e4b_schema_pins.py`: lines 29 and 33 (the two SHA-256 values
  of those goldens). Line 25 (report-trace.v1) and the docstring stay (N5).

### Test plan

- 13 PRD rows in PRD §7 order. CHAR: XT#1–3. RED: XT#4–11, XT#13. PIN: XT#12 (reads the golden
  files; RED until the regeneration).
- No stub: every test goes through `to_dict`, `to_json`, `export`, `inline_json`, `trace_dict` or
  the golden files.
- Invariants: EC-I1 (export minus `trace` == `case.to_dict()`), EC-I2 (`trace` == `trace_dict()`
  entries), EC-I3 (no member output text except `raw`/`value`; fixture limit `last_number@1`),
  EC-I4 (`case.to_dict()` has no `trace`), EC-I5 (schema id unchanged). Oracles are hand-computed
  from `combine_evidence_cases.json` and the vote/median replies.

### Acceptance

- `report.to_dict()`, `report.to_json()`, `report.export(path)` and the inline download link carry
  the same `trace` on each Case with combine evidence, as the last key (after `abstained`).
- A Case with no operations, no combine evidence, or Attempts has no `trace` and equals
  `case.to_dict()`.
- The two goldens change only by the `trace` keys (§5 step 5 check); their SHA-256 are
  `85fb1253…e5de911a` and `47c658fb…38bc390`.
- `screamingface` gates green except the append-only check, which lists only the three pinned
  files; `repo` gate green.

### Deviations

- (pre-filled) D-1: the copied `_candidate` helper computes `coverage` from its Cases instead of
  `1.0` (PRD §7 says copy it and add `operations` and `cases`). WHY: `sf.CandidateResult` refuses a
  coverage that does not match the Cases, and XT#7 holds a failed Case.
- (pre-filled) D-2: XT#7 and XT#8 each add one Case WITH combine evidence beside the Cases under
  test, so the row is RED before the change (a pure "no trace" check passes today) and a
  "trace on every Case" bug fails it.
- (pre-filled) D-3: XT#12 is a new test in `ST/test_export_trace.py`
  (`test_report_v1_goldens_hold_the_trace`) that reads the regenerated golden files with
  hand-computed oracles; the existing identity and pin tests still check the bytes.

### Notes for the review

- `S/_case_views.py:1` says the views are "Never serialized". After this unit the trace is in the
  export. Not changed here (out of the PRD scope); the reviewer or unit 5 may decide.

### Outcome (fill at the end — required before COMMIT)

- **Status:**
- **Actual files:**
- **Commits:**
- **Gates:**
- **RED log:**
- **Flakes:**
- **Approval blobs:** (path, blob at `9f42391eb`, blob after commit B — §5 command)

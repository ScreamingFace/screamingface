---
ticket: unfiled   # epic OME-1290 is the parent; the leaf is filed at PR-open
stack: screamingface, repo
status: planned   # planned | in_progress | done | blocked
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

- `docs/spec/2026-10-15-e4b-show-signals/00-overview.md` (P1–P18, N1–N5, D1–D5)
- `docs/spec/2026-10-15-e4b-show-signals/erd.md`, `contracts.md`, `test-plan.md`
- `docs/spec/2026-10-15-e4b-show-signals/prd/`: `export-trace.md` (XT, 13 rows),
  `display-format.md` (DF, 11), `case-pane.md` (CP, 17), `run-summary.md` (RS, 11), `docs.md`
  (DC, 5). 57 rows.
- `docs/plan/2026-10-15-e4b-show-signals.md`

### Units

| # | Slug | PRD rows | Stacks | Pinned files |
|---|---|---|---|---|
| 1 | export-trace | XT#1–13 | screamingface, repo | `packages/screamingface/tests/data/report_v1_combine_report.json`, `packages/screamingface/tests/data/report_v1_vote_median_report.json`, `packages/screamingface/tests/test_e4b_schema_pins.py` (lines 29, 33) |
| 2 | display-format | DF#1–11 | screamingface, repo | none |
| 3 | case-pane | CP#1–17 | screamingface, repo | none |
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
- No report-HTML test renders a Case with combine evidence (P18). The e2e reducer goldens compare
  `operation.combine.to_dict()` only (`ST/e2e/harness/reducer_golden.py:226,294`) and do not change.

### Status

Spec written. Build not started. The units append their sections (Intent, Planned changes, Pinned
edits, Test plan, Acceptance, Deviations, Outcome) below.

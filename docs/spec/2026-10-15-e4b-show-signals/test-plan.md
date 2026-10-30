# Test plan: E4b part 4 — show signals

Test ids are `<PREFIX>#<n>`, with the row number from each PRD's §7. Prefixes: `XT` export trace,
`DF` display format, `CP` Case pane, `RS` run summary, `DC` docs.

## 1. Strategy

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| Data text (member id, member value, signal key, judge model, label, source) reaches the page as HTML | H×M | unit with hostile strings | DF#5, DF#7, CP#12, RS#7 |
| The export changes a Case that has no combine step, or changes an existing key | H×M | CHAR + property over both goldens | XT#3, XT#7, XT#11 |
| The two export paths (`to_dict`, streaming JSON) disagree | H×L | unit | XT#2, XT#6 |
| A rounded number hides the stored value, or a missing value has no reason | M×H | table of hand-computed oracles | DF#3–4, DF#8–9, RS#4 |
| A plain vote, or a combine step with no evidence, shows no section (breaks ans:Q2) | M×M | unit | CP#3, CP#18 |
| The summary counts chosen or excluded wrong, or averages over None | M×M | hand-computed 3-Case oracle | RS#3, RS#6 |
| An existing HTML test breaks because of the new style or markup | M×M | CHAR + token guard | CP#1, RS#1, DF#10 |
| A public API appears (breaks ans:Q1) | M×L | the existing public surface snapshot | DF#11, `ST/test_public_surface.py` |
| The judge chip and the trace disagree | M×L | unit, one source (P12) | CP#9–11 |

## 2. TDD ground rules

- RED first. Run each new test and see it fail on the missing behavior, not on an import error. A
  new private function may exist as a stub in the RED commit. A stub that no existing path calls may
  raise `NotImplementedError`. A stub that a render path calls (`combine_sections_html`,
  `combine_summary_html`) returns `""` and is wired in the GREEN commit, so the CHAR rows and the
  existing HTML tests stay green in the RED commit.
- A `CHAR` row pins today's behavior and passes before the change. It must stay true after the
  change. It is not a RED step.
- A `PIN` row is an owner-approved edit of an existing golden; it is not a new test.
- GREEN is the smallest change. Refactor on green only.
- One behavior for each test. The test name states the behavior.
- Each user decision has a test that fails if the decision breaks:
  Q1 XT#4, CP#3, RS#3, DF#11 (+ `ST/test_public_surface.py`) · Q2 CP#3, CP#13, CP#18 · Q3 DF#3,
  DF#4, CP#4.
- Every oracle is hand-computed in the PRD (for example RS-1), never copied from the code's output.
- The test data is in the new test files (wire dicts and `_answer_fixtures.py` helpers). No new or
  changed shared data file, except the two pinned goldens of XT#12.
- A new test may import a test helper from another test module when it uses the helper as it is
  (house precedent: `ST/test_frozen_record_fields.py:24` imports `_candidate` from
  `test_report_trace`). It copies the helper only when it must change it (for example `_candidate`
  with new `operations` and `cases` parameters).

## 3. Lanes

| Lane | Where | What |
|---|---|---|
| SDK unit | `packages/screamingface/tests/` (new files below) | export, format helpers, pane, card |
| Byte goldens | `ST/test_report_v1_identity.py`, `ST/test_report_v1_vote_identity.py`, `ST/test_e4b_schema_pins.py` (existing, pinned data) | report.v1 bytes with `trace` |
| Public surface | `ST/test_public_surface.py` (existing, unchanged) | no new public name |
| Docs | `ST/test_show_signals_docs.py` (new) | README and CHANGELOG |

New test files: `ST/test_export_trace.py`, `ST/test_combine_display_format.py`,
`ST/test_combine_case_pane.py`, `ST/test_combine_run_summary.py`, `ST/test_show_signals_docs.py`.
No Engine lane, no e2e lane, no paid test. [proposed]

## 4. Aggregate

| PRD | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|
| [export-trace](prd/export-trace.md) | 3 / 2 / 6 | 13 |
| [display-format](prd/display-format.md) | 3 / 2 / 4 | 11 |
| [case-pane](prd/case-pane.md) | 5 / 4 / 7 | 18 |
| [run-summary](prd/run-summary.md) | 3 / 2 / 5 | 11 |
| [docs](prd/docs.md) | 2 / 0 / 2 | 5 |
| **Total** | **16 / 10 / 24** | **58** |

## 5. Not tested

| Item | Why | Revisit when |
|---|---|---|
| How a browser renders the table (layout, wrap, dark theme) | the house tests are string tests; the style uses theme variables only | a visual test lane exists |
| Combine steps inside Attempts | out of scope (D1); an exception to ans:Q2 that the owner approves (P15) | a reducer Benchmark declares Attempts |
| A live run | no provider call is needed: the views read decoded records | — |
| Speed of the summary on a large DiskCases run | one pass, as `abstained_count` (N4) | a user reports a slow card |

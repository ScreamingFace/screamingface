---
ticket: OME-1653   # one PR for E4b parts 4 to 7, under epic OME-1290
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

- **Status:** DONE. The code change is committed. The append-only check lists only the three
  pinned files, which the owner approves after the build.
- **Actual files:** `packages/screamingface/src/screamingface/report.py` (`_export_cases` added,
  `to_dict` uses it, `_case_entries` added, `_candidate_trace` uses it, `trace_dict` docstring);
  `packages/screamingface/src/screamingface/_report_export.py` (`iter_report_json` uses
  `_export_cases`); pinned: `packages/screamingface/tests/data/report_v1_combine_report.json`,
  `packages/screamingface/tests/data/report_v1_vote_median_report.json` (regenerated, no hand
  edit), `packages/screamingface/tests/test_e4b_schema_pins.py` (lines 29 and 33 only).
- **Commits:** code commit `e256cee02` (`feat(e4b): export the Case trace as the last key of
  report.v1 Cases`); docs commit (this ledger) follows it.
- **Gates:** `screamingface`: the append-only check FAILED and listed exactly the three pinned
  files (`tests/data/report_v1_combine_report.json`, `tests/data/report_v1_vote_median_report.json`,
  `tests/test_e4b_schema_pins.py`). With `--skip-append-only` all other gates are green: ruff
  check, ruff format --check, pyright, pytest with coverage (95 percent floor), notebooks, build,
  distribution check. `repo`: ALL GREEN, no skip flag.
- **RED log:** The RED commit `0f1e35253` was not re-run by this unit. In this unit, the focused
  file `tests/test_export_trace.py` gave 12 passed and 1 failed before the golden regeneration
  (`test_report_v1_goldens_hold_the_trace`, XT#12, the expected PIN state). After the regeneration
  and the pin edit, the focused group of §5 gave 139 passed. The golden diff proof (§5 step 5)
  passed for both files: only `trace` keys differ.
- **Flakes:** none. No test outside the focused group failed.
- **Deviations:** none. The pre-filled D-1, D-2 and D-3 are followed as written.
- **Approval blobs:** `packages/screamingface/tests/data/report_v1_combine_report.json`:
  base `3115e68f9f70c1ee16cc9fd772626ca45dd2d74a`, after commit B `390ca9ed5abf3ea512593a59c3ee0757e76e9e08`.
  `packages/screamingface/tests/data/report_v1_vote_median_report.json`: base
  `10f3247c926236629c8ece7ad05a07bf5c2e5bdb`, after commit B `cbd5d1db7c7d912b0c9b1719442da94027a35002`.
  `packages/screamingface/tests/test_e4b_schema_pins.py`: base
  `8a32a2c2f6ba4a7f8f0581e722139415e784b39b`, after commit B `e4e39af0e327d7d63f9e7d8134cb67dde359c70c`.
- **SHA-256 (new pins):** combine `85fb1253ee37e8debd0efcb5380309e5ac271aed613bfece466dc523e5de911a`;
  vote and median `47c658fbaf7d126da62fb64464c04879b2ae2c70f5f03aa9050c744bb38bc390`.

## Unit 2: display format of the Combine views (`S/_ui/combine_view.py`)

### Intent

PRD `display-format`, rows DF#1–11 (ans:Q3, ans:Q1, P5–P9, P17). A new private module
`S/_ui/combine_view.py` holds the format helpers and the style rules that units 3 and 4 use:
`number_html` (a float at 4 significant digits, `repr` as the title), `dash_html` (an em dash with
its reason as the title), `text_html` (escaped, clipped at 80 characters), `missing_reason`
(MR-1..MR-3) and the constant `STYLE` (`.sf-cmb` rules only, theme variables only, left-aligned
cells, no host zebra rows). `STYLE` is joined into `report_view._STYLE` directly after
`ACCOUNTING_STYLE`. No render path calls the helpers yet. No public name.

### Planned changes

- New `S/_ui/combine_view.py` (`STYLE`, `number_html`, `dash_html`, `text_html`, `missing_reason`,
  `__all__ = []`).
- `S/_ui/report_view.py`: import `STYLE as COMBINE_STYLE`; `_STYLE = STYLE + ACCOUNTING_STYLE +
  COMBINE_STYLE + …`.
- New test file `ST/test_combine_display_format.py`.
- Pinned edits: none.

### Test plan

- 11 PRD rows, DF#1–11, 16 collected items (DF#3 has 6 parameters). CHAR: DF#1, DF#2. RED: the
  others.
- Stub (commit A): `combine_view.py` with the four functions raising `NotImplementedError`,
  `STYLE = ""`, no `__all__`. Expected RED: 14 failed, 2 passed; no import error.
- Invariants: every data text is escaped (quote=True); a missing value always has a reason; the
  style holds no token that an existing report test forbids; no import cycle with `report_view`.

### Acceptance

- `number_html(0.123456, "x") == "<span class='sf-cmb__n' title='0.123456'>0.1235</span>"`.
- `number_html(None, "member failed: empty")` is an em dash in `sf-cmb__na` with that title.
- `text_html("x" * 81, "r") == "x" * 80 + "…"`; `text_html("<img …>", "r")` holds no `<img`.
- `missing_reason` gives `member failed: empty`, `left out by the rule: no_signal`,
  `no weight recorded` for the three statuses.
- `STYLE` is in `_STYLE` once, directly after `ACCOUNTING_STYLE`; `combine_view.__all__ == []`.
- `screamingface` gate ALL GREEN with `--base <U1>`; with `--base 9f42391eb` the append-only check
  lists only unit 1's three pinned files; `repo` gate ALL GREEN.

### Outcome (fill at the end — required before COMMIT)

- **Status:** done. Commit A (RED) and commit B (GREEN) are both on the branch.
- **Actual files:** `packages/screamingface/src/screamingface/_ui/combine_view.py` (new; the RED
  stub of commit A, then the GREEN module of commit B); `packages/screamingface/src/screamingface/_ui/report_view.py`
  (two lines: the `COMBINE_STYLE` import and the join in `_STYLE`); `packages/screamingface/tests/test_combine_display_format.py`
  (new, commit A only); this ledger. No other file changed. No pinned file changed.
- **Commits:** commit A `d0cd6dbd3` (`test(e4b): RED for the Combine display format (part 4 unit 2)`,
  as committed by the RED step). Commit B is the next commit on the branch (`feat(e4b): add the
  Combine display format helpers and style (part 4 unit 2)`), and it holds this Outcome.
- **Gates:** `screamingface --base 46641af03` (unit 1 tip): ALL GATES GREEN (append-only check
  passes, ruff check, ruff format --check, pyright, full pytest with the 95 percent floor,
  check_notebooks, uv build, check_distribution). `screamingface --base 9f42391eb`: the append-only
  check lists ONLY the three unit 1 pinned files (`tests/data/report_v1_combine_report.json`,
  `tests/data/report_v1_vote_median_report.json`, `tests/test_e4b_schema_pins.py`); the runner
  stops there, as the spec expects. `repo --base 9f42391eb`: ALL GATES GREEN, no skip flag.
  Focused: `tests/test_combine_display_format.py` gives `16 passed`; the 8 existing report test
  files give `96 passed`.
- **RED log:** `uv run pytest tests/test_combine_display_format.py -q` gives `14 failed, 2 passed
  in 0.10s` (matches §3.2). Passed: `test_score_text_keeps_six_significant_digits`,
  `test_cost_cell_dash_has_a_title`. Failed with `NotImplementedError` (`_ui/combine_view.py` lines
  18, 22, 26, 30): the 6 items of `test_number_shows_four_significant_digits_and_the_exact_title`,
  `test_missing_number_is_an_em_dash_with_its_reason`, `test_reason_in_the_title_is_escaped`,
  `test_text_cell_clips_at_80_characters`, `test_text_cell_escapes_markup`,
  `test_missing_text_is_an_em_dash_with_its_reason`, `test_missing_reason_follows_the_status`.
  Failed with `AssertionError`: `test_combine_style_is_scoped_themed_and_has_no_banned_token`
  (`''.startswith('<style>')`), `test_combine_view_adds_no_public_name` (`None == []`). No import
  error. Also at commit A: `ruff check` and `ruff format --check` exit 0 on the two new files;
  `pyright` 0 errors; the second focused command (8 existing report test files) gives `96 passed`.
- **Deviations:** (pre-filled)
  - D-1: the PRD writes the `.sf-cmb__t`, `.sf-cmb__t th` and `.sf-cmb__t td` rules on one line
    each; two of those lines are 191 and 128 characters and fail ruff E501 (line length 100). The
    module wraps the three rules inside their declaration blocks (newline plus two spaces, the
    `accounting_view.STYLE` precedent). Same selectors, declarations and order.
  - D-2: planner additions to the PRD oracles, same behavior: DF#6 also checks clip-then-escape
    (`"<" * 81` → `"&lt;" * 80 + "…"`) and that `""` stays `""`; DF#10 also checks that nothing is
    outside the rules, that there is no `rgb`, and that every `color:` value is a `var(--sf-…)`
    (PRD §4 theme NFR).
  - D-3: DF#9 copies the Engine wire `rank_cut_not_met` into the test as `_RANK_CUT_NOT_MET`
    (the SDK fixture file does not hold it), as the case-pane PRD §7 does.
  - D-4: the RED stub has no `__all__`, so DF#11 fails on a value at commit A; the
    `report_view` join is in commit B only (with `STYLE = ""` it is a no-op).
- **Pinned edits:** none.

## Unit 3: the Combine section of the Case pane (`case-pane`)

### Intent

PRD `case-pane`, rows CP#1–18 (ans:Q1 "Case pane table", ans:Q2 "Every reducer step", ans:Q3;
P8–P12, P15, P16, P18–P20). The "Answer & grading" view of each Case pane shows one Combine
section per combine step, between the failures and the criteria: the step chips (F1–F10), one row
per member (C1–C8) and the tally. A combine step with no evidence gets a short section with an
`evidence · —` chip (P19). A Case with no combine step renders as before. All data text is escaped.
No public name, no new bound, no change to the trace, the export or any record.

### Planned changes

- `S/_ui/combine_view.py`: `combine_sections_html` (called by the pane), `_is_combine`, `_label`,
  `_table` (shared with unit 4, P20), `_heading`, `_no_evidence_section`, `_section`, `_chips`,
  `_result_chip`, `_reads_chip`, `_judge_chip`, `_signal_head`, `_member_row`, `_number_cell`,
  `_tally_html`; constants `_NUMBER_COLUMNS`, `_NO_EVIDENCE`, `_NO_JUDGE_MODEL`.
- `S/_ui/report_view.py`: import `combine_sections_html`; `_pane_html` puts it between
  `_case_failures_html(case)` and the criteria.
- New test file `ST/test_combine_case_pane.py` (CP#1–18).
- Pinned edits: none.

### Test plan

- 18 PRD rows in the PRD §7 order. CHAR: CP#1, CP#2. RED: CP#3–18.
- Stub (commit A): `combine_sections_html` returns `""` and is not called; each RED test fails on
  an assertion, never on an import error.
- Every oracle is hand-written from CP-1..CP-E4 and CP-D1..CP-D7.

### Acceptance

- A plain majority vote (`vote_one_failed`) shows its whole section (CP-1 exact string).
- The rank step shows `cut · top 3 · max`, the excluded member with its reason, scores and ranks.
- The declared signal header names its source; the judge chip names the judge model or shows a
  dash; a step that reads no judge has no judge chip.
- Hostile text is escaped; two combine steps give two sections in order; a step with no evidence
  gives the short section.
- `screamingface --base <U2>` all green; `screamingface --base 9f42391eb` red only on the unit 1
  pinned files; `repo` green.

### Outcome (fill at the end — required before COMMIT)

- **Status:** done. The GREEN code of the Case pane Combine section is on the branch. All 18 CP
  rows pass. The gates are green, except the append-only check of `--base 9f42391eb`, which
  lists only the three unit 1 pinned files (see Gates).
- **Actual files:** `packages/screamingface/src/screamingface/_ui/combine_view.py` (the commit A
  stub replaced by the GREEN code: imports, three constants, `combine_sections_html` and its
  private helpers); `packages/screamingface/src/screamingface/_ui/report_view.py` (one import
  line and the `body` expression of `_pane_html` with `combine_sections_html(candidate, case)`
  between the failures and the checks); this ledger. The test file
  `packages/screamingface/tests/test_combine_case_pane.py` was added in commit A only and is not
  changed. No pinned file changed.
- **Commits:** commit A `b912ae0c3` (`test(e4b): RED for E4b part 4 unit 3 case-pane`, as
  committed by the RED step). Commit B is the next commit on the branch (`feat(e4b): show a
  Combine section for each reducer step in the Case pane (part 4 unit 3)`), and it holds this
  Outcome. No commit C: spec §7 asks for no docs in this unit (unit 5 holds README and CHANGELOG).
- **Gates:** `screamingface --base 9f42391eb`: the append-only check lists ONLY the three unit 1
  pinned files (`tests/data/report_v1_combine_report.json`,
  `tests/data/report_v1_vote_median_report.json`, `tests/test_e4b_schema_pins.py`). This is the
  expected result. Rerun with `--skip-append-only`: ALL GATES GREEN (ruff check, ruff format
  --check, pyright, full pytest with the 95 percent floor, check_notebooks, uv build,
  check_distribution). `screamingface --base d49e75ab2` (unit 2 tip): ALL GATES GREEN, the
  append-only check included, with no skip flag. `repo --base 9f42391eb`: ALL GATES GREEN.
  Focused: `tests/test_combine_case_pane.py` gives `18 passed`; the 19 other test files of the
  second focused command of spec §5 give `301 passed`. `ruff check`, `ruff format --check` and `pyright`
  are clean on the three touched Python files.
- **RED log:** the RED step recorded the commit A state (commit message: 16 rows fail on an
  assertion, 2 CHAR rows pass). This unit did not run the RED check again: commit A is not
  checked out in this worktree.
- **Deviations:** (pre-filled)
  - D-1: CP-E3 / CP#12 part 2. The PRD wire declares the name `<b>k</b>`
    (`declared {"<b>k</b>": {"source": "<x>"}}`). The SDK decoder refuses it: a declared NAME must
    be a signal name (`is_signal_name`, `[a-z][a-z0-9_]{0,31}`;
    `S/combine_evidence.py:391-402` `_declared_map`, "Combine evidence declared names must be declared
    signal names"). The PRD sentence "The SDK decoder accepts both" is true only for the signal
    key and the source. The test keeps both hostile strings on two columns: the plain signal key
    `<b>k</b>` (header `<th scope='col'>&lt;b&gt;k&lt;/b&gt;</th>`, no title) and the declared name
    `conf` with the source `<x>` (header `<th scope='col' title='source: &lt;x&gt;'>conf</th>`).
    The P8 coverage is the same.
  - D-2: CP-D4 / CP#8. The PRD oracle "no `<th scope='col'>score</th>`" for `vote_one_failed`
    is false by construction: the tally table has its own `score` header cell. The test asserts the
    whole member header `member, status, value, chosen`, no `weight` and no `rank` header, and
    exactly one `score` header (the tally).
  - D-3: CP-D6 / CP#16. `case.to_dict()` of the 256-member Case is 65,123 characters, not "about
    51,000" (the PRD estimate). The oracle (> 32,000, so the preview falls back) holds.
  - D-4: the PRD names six functions; the code has nine more private helpers so that each function
    stays inside the SDK ruff limits (C901 8, PLR0912 7, PLR0911 3). Behavior is the PRD §2 text.

## Unit 4: the run summary in the Candidate card (`combine_summary_html`)

### Intent

PRD `run-summary`, rows RS#1–11 (ans:Q1 "Run-level summary", ans:Q2, ans:Q3; P5, P8, P13, P14,
P15, P19, P20). Each Candidate card gets one "combine" block after the members block and before
the accounting note. For each reducer step (combine `operation_id`), it shows the heading
`{label} · {reducer} · N case|cases` and one row per member: chosen `{count} of {N}`, excluded
`{count} of {N}`, and per declared signal the `math.fsum` mean (4 significant digits, the exact
value as the title) with its count `n`. No block when no Case has combine evidence. Private code
only; no public name.

### Planned changes

- `S/_ui/combine_view.py`: `combine_summary_html(candidate)`, `_StepSummary` (private mutable
  dataclass), `_summary_html`, `_member_row`, `_mean_cell`; imports `math`, `dataclass`, `field`.
  Reuses unit 2's `number_html` and unit 3's `_label` and `_table`.
- `S/_ui/report_view.py`: import `combine_summary_html`; one line in `_card_html` between
  `_members_html(candidate)` and `run_accounting_note(...)`.
- New test file `ST/test_combine_run_summary.py` (11 tests).

### Pinned edits

None.

### Test plan

- 11 PRD rows, RS#1–11, in the PRD §7 order. CHAR: RS#1 (no evidence → no block), RS#2 (grid
  before URL4). RED: RS#3–11.
- Stub (commit A): `combine_summary_html` returns `""`, not wired. Each RED test fails on an
  AssertionError, never on an import error.
- Oracles hand-computed in the PRD: RS-1 means 80, 65, 45 (n 3, 2, 2), counts `2 of 3`, `1 of 3`,
  `0 of 3`, member_3 excluded `1 of 3`; RS-2 title `0.15000000000000002`, text `0.15`.

### Acceptance

- RS#1–11 pass; the RED run was 9 failed, 2 passed.
- No existing test file changes in this unit; the append-only check against the unit 3 tip is green.
- `screamingface` gate green except the append-only check against `9f42391eb`, which lists only
  the three unit 1 pinned files; green with `--skip-append-only`. `repo` gate green.

### Deviations

- D-1 (PRD §4 NFR wording): the NFR says memory is O(steps × members × signal names), not O(Cases).
  The PRD §2 data shape keeps each non-None value in `values: dict[tuple[str, str], list[float]]`,
  because `math.fsum` needs every value for the exact sum. So memory holds one float per member,
  signal key and Case. This unit follows the §2 shape. Time is still one pass over the Cases.
- D-2 (addition): RS#10 also checks the members block and the accounting note around the summary
  (contract C3 "after the members block and before the accounting note"). So the test copy of
  `_candidate` takes `members` and builds a Fusion card.
- D-3 (oracle refinement): RS-D1 says "the card holds `a&lt;b&gt;`". The folded URL4 steps list
  holds that text already today, so RS#7 checks the full summary heading string instead.
- D-4 (helpers): `_member_row` and `_mean_cell` are two private helpers that the PRD does not name.
  They split `_summary_html`; the output is the PRD §2 markup.

### Outcome (fill at the end, before commit B)

- **Status:** done. The GREEN code of the run summary is on the branch. RS#1–11 pass (11 passed).
  The gates are green, except the append-only check of `--base 9f42391eb`, which lists only the
  three unit 1 pinned files (expected). `repo` is green.
- **Actual files:** `packages/screamingface/src/screamingface/_ui/combine_view.py` (the commit A
  stub replaced by the GREEN code: imports `math`, `dataclass`, `field`; `combine_summary_html`,
  `_StepSummary`, `_summary_html`, `_summary_row`, `_mean_cell`); `packages/screamingface/src/screamingface/_ui/report_view.py`
  (the import of `combine_summary_html` and one line in `_card_html` between the members block
  and the accounting note); this ledger. The test file `packages/screamingface/tests/test_combine_run_summary.py`
  was added in commit A only and is not changed. No pinned file changed.
- **Commits:** A = `bd00dcf71` (`test(e4b): RED for E4b part 4 unit 4 run-summary`, as committed by
  the RED step). B is the next commit on the branch (`feat(e4b): show the run summary of each
  reducer step in the Candidate card (part 4 unit 4)`), and it holds this Outcome. No commit C:
  spec §7 asks for no docs in this unit (unit 5 holds README and CHANGELOG).
- **U3 (unit 3 tip):** `8c90a6615`. `git diff 8c90a6615 -- packages/screamingface/tests
  apps/screamingface-engine/tests` lists only `tests/test_combine_run_summary.py` (new, 482
  insertions). So the append-only check against U3 has no modified or deleted test: green.
- **RED log:** the RED run of commit A gave `9 failed, 2 passed`. The nine FAILED lines were:
  `test_summary_counts_chosen_excluded_and_means_the_declared_signal`,
  `test_mean_title_shows_the_exact_value`,
  `test_summary_without_declared_signals_shows_chosen_and_excluded_only`,
  `test_signal_with_no_value_in_any_case_shows_a_dash_and_n_zero`,
  `test_labels_and_sources_are_escaped`, `test_two_steps_give_two_blocks_in_first_seen_order`,
  `test_cases_without_case_operations_are_ignored`,
  `test_summary_sits_after_the_grid_and_before_the_url4_block`,
  `test_one_case_heading_is_singular`. Each one is an `AssertionError`. The two CHAR rows
  (`test_card_without_combine_evidence_has_no_summary`, `test_card_shows_the_grid_before_the_url4_block`)
  passed.
- **Gates:**
  - `screamingface --base 9f42391eb`: the append-only check lists ONLY the three unit 1 pinned
    files (`tests/data/report_v1_combine_report.json`, `tests/data/report_v1_vote_median_report.json`,
    `tests/test_e4b_schema_pins.py`). Rerun with `--skip-append-only`: ALL GATES GREEN (ruff check,
    ruff format --check, pyright, pytest with the 95 percent floor, check_notebooks, uv build,
    check_distribution). The first such run had one failed test (see Flakes); the rerun was green.
  - `ruff check`, `ruff format --check` and `pyright` (basic) are clean on the SDK package.
  - Focused: `tests/test_combine_run_summary.py` gives `11 passed`. The 18 neighbour files of the
    spec §5.2 second command give `262 passed`.
  - `repo --base 9f42391eb`: ALL GATES GREEN.
- **Flakes:**
  - `tests/test_connection_panel.py::test_panel_starts_oauth_and_polls_without_blocking_the_notebook`
    failed once in the first full `screamingface` run (`1 failed, 4489 passed`). It passes alone
    (`1 passed`) and the whole file passes (`39 passed`). The next full run passed it. It is not in
    the OME-1619 list. It is recorded here as a flake. It is not changed.
- **Deviations:**
  - D-1 … D-4 above (the planner's deviations).
  - D-5: the helper `_member_row` of the spec §2.1b code has the same name as the unit 3 helper
    `_member_row(row, evidence, columns, keys)` in the same module. The second `def` would replace
    the first. Unit 3's Case pane call would then get the wrong function (pyright: `reportRedeclaration`
    and `reportCallIssue`). So the run-summary helper is named `_summary_row`. Its body and signature
    are the spec code. No unit 2 or unit 3 code changed.

## Unit 5: docs (README and CHANGELOG)

### Intent

Tell the SDK user where part 4 shows the combine data (ans:Q1): the Combine section in the Case
pane for every reducer step (ans:Q2), the run summary in each Candidate card, and the `trace` key
in the JSON export. Say how numbers read (ans:Q3) and what the export holds (P1, N1). Docs only:
no code, no snapshot, no golden and no url4 change.

### Planned changes

- `packages/screamingface/README.md` — R1: the `### Deterministic synthesizers` sentence about
  report.v1 now names the `trace` key and the new section (3 lines replaced by 4). R2: the new
  section `### Combine steps in the report` between `### Browse completed Case results` and
  `### Completed accounting breakdown`.
- `packages/screamingface/CHANGELOG.md` — B1: one part 4 bullet, the first under the first
  `### Features` of `## Unreleased`, before the part 3 "Signal sources" bullet.
- New `packages/screamingface/tests/test_show_signals_docs.py` — DC#1–DC#5. It imports `_section`
  from `test_evidence_completeness_docs` (house precedent `ST/test_frozen_record_fields.py:24`).

### Pinned edits

None.

### Test plan

- DC#1 CHAR (Browse before Accounting). DC#2 the new section, its place and its phrases. DC#3 the
  Deterministic synthesizers sentence. DC#4 one part 4 bullet, first under the first Features
  list, before the part 3 bullet. DC#5 the bullet holds no token that other docs tests count.
- Regression (CHAR, no edit): `test_evidence_completeness_docs.py`, the CHANGELOG checks of
  `test_pick_output.py` and `test_mean.py`, the two recipe README tests, the Fusion doc goldens.

### Acceptance

- DC#1–DC#5 green; the regression tests green.
- README diff: 3 removed lines, 34 added lines, no added line over 100 characters.
- `run_gates.py screamingface --base <unit 4 tip>`: all green, append-only included.
- `run_gates.py screamingface --base 9f42391eb`: append-only offenders are only the three unit 1
  pinned files; with `--skip-append-only` all green. `run_gates.py repo --base 9f42391eb`: green.

### Unit 5 outcome

- **Status:** done. Commit A (RED) is the first commit of this unit; commit C is the docs.
- **Actual files:** `packages/screamingface/tests/test_show_signals_docs.py` (new), `packages/screamingface/README.md` (R1, R2), `packages/screamingface/CHANGELOG.md` (B1), this ledger.
- **Commits:** A = `bf00699a8` — test(e4b): RED for E4b part 4 unit 5 docs; C = (see `git log`) — docs(e4b): README and CHANGELOG for the combine views (part 4).
- **Unit 4 tip (base of the unit 5 append-only check):** `d7754f48a`.
- **RED record (commit A):** 4 failed (DC#2-5, each on a doc assertion), 1 passed (DC#1 CHAR).
  Regression set (`test_evidence_completeness_docs.py`, `test_pick_output.py`, `test_mean.py`,
  `test_signal_recipes_readme.py`, `test_combine_recipes_readme.py`, `test_fusion_doc_goldens.py`):
  83 passed. `ruff format --check`, `ruff check` and `pyright` are clean on the new file.
- **Gates:** `screamingface --base d7754f48a` (unit 4 tip): all green, append-only included.
  `screamingface --base 9f42391eb`: append-only offenders are only the three unit 1 pinned files
  (`tests/data/report_v1_combine_report.json`, `tests/data/report_v1_vote_median_report.json`,
  `tests/test_e4b_schema_pins.py`); with `--skip-append-only` all green. `repo --base 9f42391eb`:
  all green. Flakes: none.
- **Deviations:**
  - The heading uses a colon (`## Unit 5: ...`) like the units 1–4 headings, not an em dash.
  - README planner additions A1–A5 (not in the PRD delta text, true for the unit 1–4 code, not
    tested): A1 a step with no evidence record shows `evidence` and an em dash (P19); A2 a Case
    with no combine evidence has no `trace` key (P1, XT-E1); A3 the combine steps of an Attempt
    are not in the pane, the summary or the export (P15, owner approval pending); A4 the
    `whole@1`/`json_object@1` text is in the export two times (N1); A5 a member value over 80
    characters ends with `…`, and the full value is in the export and in `case.answers()` (P7).
  - DC#2 also checks `whole@1` and `json_object@1` (N1). DC#3 also checks the `(see "Combine steps
    in the report")` link and the unchanged `report.v1` phrase. DC#4 also checks that the second
    bullet is the part 3 "Signal sources" bullet.
  - Order of commits: the README and CHANGELOG edits were checked (focused tests, diff counts)
    before commit C; the gate run follows commit C, as the spec says.

## Owner approvals (2026-10-15)

- The owner approved the three unit 1 pinned edits (the two report.v1 goldens and the two SHA-256
  lines in `ST/test_e4b_schema_pins.py`). Manifest: `.claude/test-change-approvals/OME-E4B-P4.json`
  (placeholder id; rename at PR-open).
- P1 approved: `trace` is an additive key under the same id `screamingface.report.v1`.
- P15 approved: the combine steps of Attempts are not shown or exported in this part; follow-up when a
  reducer Benchmark declares Attempts.
- The evidence key order `signal, cut, declared, result` is confirmed and is written in the part 3
  contract C6.
- The build errata E1–E4 are in the spec overview §9.
- Part 4 was rebased onto the part 3 tip that holds the key-order note (docs-only change).

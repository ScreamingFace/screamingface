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

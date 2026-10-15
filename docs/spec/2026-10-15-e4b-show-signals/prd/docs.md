# PRD: README and CHANGELOG for the Combine views

**Source:** ans:Q1–Q3 (the user sees the new surfaces) · **Priority:** P2
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: `packages/screamingface/README.md`, `packages/screamingface/CHANGELOG.md`

## 1. Summary and user story

As a researcher who reads the SDK README, I want to know where the report shows the combine data,
how its numbers read, and what the export holds, so that I can read and share the evidence.

## 2. Background and constraints

- The README says today: "`report.trace_dict()` is `screamingface.report-trace.v1`, and
  `report.to_dict()` and `report.export()` stay `report.v1`."
  [existing packages/screamingface/README.md:389-392]
- The README has `### Browse completed Case results` (line 1333) and then
  `### Completed accounting breakdown` (line 1362) under `## Progress and Reports`.
  [existing packages/screamingface/README.md:1218,1333,1362]
- Other docs tests read the CHANGELOG `## Unreleased` bullets. They count or pick bullets by these
  tokens, so the part 4 bullet must not hold any of them: `` `output_missing` ``
  (ST/test_pick_output.py:273), `` `sf.Pick( `` and `` `sf.Mean( `` (ST/test_mean.py:218-221, the
  FIRST bullet that names it), `` `no_weight` ``, `` `sf.report.CombineCut` ``,
  `` `judge_operation_id` ``, `` `sf.JudgeWriterWarning` `` (ST/test_evidence_completeness_docs.py:98-106,
  exactly one bullet each, in a fixed order after the pick-output bullet).
  [existing]
- The part 2 docs test reads the section `### Deterministic synthesizers` and checks fixed phrases
  and counts in it. The README edit must keep each of them. [existing ST/test_evidence_completeness_docs.py:47-63]

### 2.1 Current behavior

No README text and no CHANGELOG bullet name the Combine section, the run summary or the `trace`
export key.

**Delta.**

1. README, `### Deterministic synthesizers`: replace the sentence
   "`report.trace_dict()` is `screamingface.report-trace.v1`, and `report.to_dict()` and
   `report.export()` stay `report.v1`." with
   "`report.trace_dict()` is `screamingface.report-trace.v1`. `report.to_dict()` and
   `report.export()` stay `report.v1`, and each Case with a combine step also has a `trace` key
   with the same entries (see "Combine steps in the report")."
2. README: a new section `### Combine steps in the report` between `### Browse completed Case results`
   and `### Completed accounting breakdown`. It has three bold paragraphs:
   - "**The Case pane.**" — every reducer step of a Case has a Combine section: the step facts
     (reducer, rule, result, cut, the signal it reads, the judge model, agreement, tie, dropped), and
     one row per member (status and reason, value, weight, score, rank, each signal, chosen). A
     plain vote has its section too. A declared signal column names its source on hover.
   - "**The run summary.**" — each Candidate card has one table per reducer step: how often each
     member was chosen, how often it was excluded, and the mean of each declared signal with `n`,
     the number of Cases that gave a value.
   - "**The export.**" — `report.export()` and `report.to_dict()` add a `trace` key to each Case
     with a combine step. It holds the same entries as `report.trace_dict()`. The trace has no
     member output text. The other keys do not change, and the schema stays `report.v1`.
   And one sentence: "Numbers show 4 significant digits; hover a number to see the exact stored
   value. A missing value is an em dash; hover it to see why."
3. CHANGELOG, `## Unreleased`, `### Features`: one new bullet, the first bullet of that list (before
   the part 3 "Signal sources" bullet). Proposed text:
   "* **screamingface:** show the combine steps in the report (E4b part 4). The Case pane has a
   Combine section for every reducer step, with the step facts and one row per member (status and
   reason, value, weight, score, rank, each signal, chosen). Each Candidate card has a summary per
   reducer step: how often each member was chosen and excluded, and the mean of each declared
   signal with its count. Numbers show 4 significant digits, the exact value on hover, and a
   missing value is an em dash with its reason. `report.export()` adds a `trace` key to each Case
   with a combine step (the `report.trace_dict()` entries); the schema stays `report.v1`. No new
   Python API. No Engine change."

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **DC-1** Given the README, then the section `### Combine steps in the report` exists, after
  `### Browse completed Case results` and before `### Completed accounting breakdown`, and it holds
  `**The Case pane.**`, `**The run summary.**`, `**The export.**`, `4 significant digits`,
  `an em dash`, `` `trace` `` and `` `report.trace_dict()` ``. [stated ans:Q1–Q3]
- **DC-2** Given the CHANGELOG, then exactly one `## Unreleased` bullet holds `E4b part 4`; it is the
  first bullet after `### Features`; it ends with `No Engine change.` [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **DC-D1** (M×M) [existing] The part 4 bullet holds none of the tokens of §2, so the existing docs
  tests keep their counts.
- **DC-D2** (M×L) [proposed] The `### Deterministic synthesizers` section holds
  `each Case with a combine step also has a `trace` key`.

## 4. Non-functional requirements

- ASD-STE100 style for the README text and the bullet. [stated prompt]

## 5. Out of scope

- A screenshot or a notebook example. [proposed]

## 6. Open questions

None.

## 7. TDD plan

Test file: `ST/test_show_signals_docs.py` (new). Copy `_section` and `_unreleased_entries` from
`ST/test_evidence_completeness_docs.py:30-45` (do not import private helpers of another test
module).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `readme_has_the_browse_and_accounting_sections_in_order` | unit | [existing README.md:1333,1362] | L×L | passes today and after |
| 2 | `readme_documents_the_combine_section_the_summary_and_the_export` | unit | DC-1 | M×M | new README section |
| 3 | `deterministic_synthesizers_section_points_to_the_trace_key` | unit | DC-D2 | L×M | README sentence |
| 4 | `changelog_has_one_part_4_bullet_first_in_features` | unit | DC-2 | M×M | new bullet |
| 5 | `part_4_bullet_holds_no_token_that_other_docs_tests_count` | unit | DC-D1 | M×M | bullet text |

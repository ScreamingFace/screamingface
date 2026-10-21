# PRD: README and CHANGELOG for consistency

**Source:** ans:Q3, ans:Q4 (the author writes and reads the source); epic ("N extra calls per
member") · **Priority:** P2
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: `packages/screamingface/README.md`, `packages/screamingface/CHANGELOG.md`

## 1. Summary and user story

As a benchmark author who reads the SDK README, I want one section that shows how to declare
`sf.Consistency`, what the number means, what it costs, what happens when an extra call fails, and
how the report shows it, so that I can copy a recipe that the Engine tests prove.

## 2. Background and constraints

- README headings on `633fec3a1`: `### Signal sources` (line 930), `### Gate the majority`
  (1048), `### Fusion as a named recipe` (1135), `## Install` (1172), `### Browse completed Case
  results` (1421), `### Combine steps in the report` (1450), `### Completed accounting breakdown`
  (1490). [existing]
- `ST/test_gate_docs.py:100` pins the headings between `### Signal sources` and
  `### Fusion as a named recipe` to `[Signal sources, Gate the majority]`. So the new section
  CANNOT go there. It goes after `### Fusion as a named recipe` and before `## Install`; no test
  pins that range. [existing]
- `ST/test_show_signals_docs.py:78` and `ST/test_gate_docs.py:150` pin the headings between Browse
  and Accounting to `[Browse, Combine]`: no new heading may go there. A new paragraph inside
  `### Combine steps in the report` is allowed. [existing]
- `ST/test_show_signals_docs.py` pins bullets 0 and 1 of the first `### Features` list of
  `## Unreleased`; `ST/test_gate_docs.py` pins the part 5 bullet at position 2. The part 7 bullet
  goes after the part 5 bullet (position 3 on this base). Part 6 builds in parallel and may also add
  a bullet; the test checks the ORDER (after the part 5 bullet), not a fixed index. [existing];
  [proposed]
- The part 7 bullet must hold none of the counted tokens of `ST/test_show_signals_docs.py:24-35`
  (`` `output_missing` ``, `` `sf.Pick( ``, `` `sf.Mean( ``, `` `no_weight` ``,
  `` `sf.report.CombineCut` ``, `` `judge_operation_id` ``, `` `sf.JudgeWriterWarning` ``) and
  not the texts `E4b part 4` or `E4b part 5`. [existing]

### 2.1 Current behavior

No README text and no CHANGELOG bullet name `sf.Consistency`.

**Delta.**

1. README: a new section `### Consistency samples` directly after the `### Fusion as a named
   recipe` section and before `## Install`. It holds, in this order:
   - one paragraph: what the source does ("each member makes `n` more calls with distinct seeds at
     the stated `temperature`; its other params do not change"), what the number is (the share of
     the extra answers that equal the member's answer after the step's own extract and normalize;
     a step that has no extract, such as `sf.Pick(by_signal=...)`, compares the last line with the
     `text` normalizer), and that the extra answers never vote;
   - the cost sentence, verbatim: "Each member makes n more calls on every Case: a Fusion of M
     members makes M × n extra calls, and you pay for them. The extra calls run also when the
     member call fails.";
   - the failure sentence, verbatim: "A failed extra call does not fail the Case: the value is the
     share of matches over the extra calls that answered, and when every extra call fails, the
     value is missing.";
   - the seed sentence, verbatim: "The extra calls use fixed seeds that the recipe sets, so a
     replay returns the same samples; they do not change with the run seed.";
   - the preflight sentence, verbatim: "The free preflight checks that each member's model takes
     `seed` and `temperature` before any call.";
   - the rules: one `sf.Consistency` per Fusion; each member is one `sf.Model`; `n` from 1 to 32;
     at most 1024 extra calls per Fusion; not inside a corrective loop in this version;
   - one `python` code block that assigns `c1_pick_most_consistent` and `c2_median_consistency`,
     each equal to the builder of the same fixture in `ST/test_consistency_contract_fixtures.py`
     (F1, F2);
   - one sentence for a weight: "`sf.Vote(weights=sf.signal(\"cons\"))` weights each member by its
     value; a member with the value 0 has no weight and does not vote.";
   - one sentence that points to the report: "The Case pane, the run summary and the export show
     the value and the failed extra calls (see "Combine steps in the report").".
2. README `### Combine steps in the report`: one new paragraph that starts with
   `**Consistency.**` and names the chip text `samples · cons · 4 per member · failed 6 of 12`,
   the cell note `2 failed`, the summary line `samples · cons · failed 12 of 24`, and the export key
   `operations[].combine.consistency`.
3. CHANGELOG: one bullet in the first `### Features` list of `## Unreleased`, directly after the
   part 5 bullet, that starts with `**screamingface:** measure how often a member repeats its
   answer (E4b part 7).` and ends with `**Requires an SF Engine with the E4b part 7 consistency
   source.**`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **DC-1** Given the README, then `### Consistency samples` comes after `### Fusion as a named
  recipe` and before `## Install`, it states the rules and the four verbatim sentences, and its
  code block compiles to the two consistency fixtures. [proposed]
- **DC-2** Given the CHANGELOG, then exactly one bullet holds `E4b part 7`, and it comes after the
  part 5 bullet in the first `### Features` list. [proposed]

### 3.2 Error paths

None.

### 3.3 Derived scenarios

- **DC-D1** (M×M) [proposed] The `### Combine steps in the report` section holds
  `**Consistency.**` and `operations[].combine.consistency`, and the headings between Browse and
  Accounting are still `[Browse, Combine]`.
- **DC-D2** (M×M) [existing] The part 7 bullet holds none of the counted tokens, so every existing
  docs test keeps its count and its pick.

## 4. Non-functional requirements

- Plain words, in the house style of the part 3 and part 5 sections.

## 5. Out of scope

- An E4c text.

## 6. Open questions

None.

## 7. TDD plan

New test file: `ST/test_consistency_docs.py`. It imports `_section` from
`test_evidence_completeness_docs`, `_COUNTED_TOKENS`, `_first_features_bullets`, `_unreleased` from
`test_show_signals_docs`, and the two builders from `test_consistency_contract_fixtures`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `readme_keeps_the_fusion_install_and_report_anchors` (`### Gate the majority`, `### Fusion as a named recipe`, `## Install`, `### Combine steps in the report`, `### Completed accounting breakdown`, each once, in this order) | unit | — | M×M | passes today |
| 2 | `readme_consistency_section_sits_before_install_and_states_the_rules` (order check; the four verbatim sentences; phrases `sf.Consistency(n=`, `temperature`, `1 to 32`, `1024`, `corrective loop`, `never vote`) | unit | DC-1 | M×M | README |
| 3 | `readme_consistency_recipes_compile_to_the_fixtures` (one `python` code block; `exec`; each name compiles to its fixture byte for byte) | unit | DC-1 | H×M | README code block |
| 4 | `combine_report_section_names_consistency` | unit | DC-D1 | M×L | README paragraph |
| 5 | `changelog_has_one_part_7_bullet_after_part_5_without_counted_tokens` | unit | DC-2, DC-D2 | M×M | CHANGELOG |

Pinned edits of this PRD: none.

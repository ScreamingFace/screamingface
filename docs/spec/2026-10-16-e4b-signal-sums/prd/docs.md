# PRD: README and CHANGELOG for signal sums and the abstain band

**Source:** ans:Q1, ans:Q2 (the user writes and reads sums and bands) · **Priority:** P2
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: `packages/screamingface/README.md`, `packages/screamingface/CHANGELOG.md`

## 1. Summary and user story

As a benchmark author who reads the SDK README, I want one section that shows how to declare a sum
of signals, how a rule or a gate reads it, how the abstain band works, and how the report shows
both, so that I can copy two recipes that the Engine tests prove.

## 2. Background and constraints

- README headings on `633fec3a1`: `### Signal sources` (line 930), `### Gate the majority` (1048),
  `### Fusion as a named recipe` (1135), `## Install` (1172), `### Browse completed Case results`
  (1421), `### Combine steps in the report` (1450), `### Completed accounting breakdown` (1490).
  [existing]
- `ST/test_gate_docs.py:100` pins the headings between Signal sources and Fusion as
  `[_SIGNALS, _GATE]`: no new heading may go there. `ST/test_gate_docs.py:133` pins exactly one
  python code block in `### Gate the majority`. [existing]
- `ST/test_show_signals_docs.py:78` and `ST/test_gate_docs.py:150` pin the headings between Browse
  and Accounting (`[_BROWSE, _COMBINE]`). A new paragraph inside `### Combine steps in the report`
  is allowed (phrase checks only). [existing]
- No test pins the headings between `### Fusion as a named recipe` and `## Install`. The new
  section goes there. [existing, checked with grep]
- `ST/test_gate_docs.py:161-168` pins the first `### Features` list of `## Unreleased`: bullet 0
  part 4, bullet 1 part 3, bullet 2 part 5. The part 6 bullet goes at position 3. [existing]
- The part 6 bullet holds none of the counted tokens (`ST/test_show_signals_docs.py:27-35`:
  `` `output_missing` ``, `` `sf.Pick( ``, `` `sf.Mean( ``, `` `no_weight` ``,
  `` `sf.report.CombineCut` ``, `` `judge_operation_id` ``, `` `sf.JudgeWriterWarning` ``), and
  none of the texts `E4b part 3`, `E4b part 4`, `E4b part 5` (other docs tests count the bullets
  that hold them). [existing]

### 2.1 Current behavior

No README text and no CHANGELOG bullet name `sf.Sum`, `abstain_band` or `in_band`.

**Delta.**

1. README: a new section `### Sum signals and the abstain band` directly after the
   `### Fusion as a named recipe` section and directly before `## Install`. It holds, in this
   order:
   - one paragraph on `sf.Sum`: `signals={"risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}), ...}`
     gives each member `risk = 0.5 × sev_a + 0.3 × sev_b`; each component is another declared name
     of the same Fusion, never an E4a key and never another `sf.Sum`; 1 to 7 components; each
     coefficient is a finite number that is not zero; the sum counts toward the 8 names;
   - the missing rule, verbatim: "When a component is missing, the sum is missing, not zero. A rule
     leaves the member out, as for any declared signal.";
   - the arithmetic sentence, verbatim: "The Engine adds the exact products and rounds once, so
     the order of the components does not change the value.";
   - one sentence: a rule or a gate reads the sum by its name: `sf.Pick`, `sf.Rank`, `sf.Filter`,
     a vote weight, and a gate on `"chosen:risk"` or `"mean:risk"`;
   - the weight sentence: a sum that adds `sf.Logprob("mean")`, `sf.Logprob("sum")` or
     `sf.Entropy(...)` cannot be a vote weight; a sum of zero or less, or too large to be a
     weight, gives the member no weight;
   - one paragraph on the band: `sf.Gate(..., abstain_band=(lo, hi))`; the band is closed (both
     ends are in it); the Engine checks the band before the comparison; inside the band the Case
     abstains with `in_band` for every `otherwise`; outside it the gate compares as before; a
     missing number skips the band; the gate record shows `"branch": "band"`; coverage counts the
     Case with the other abstains;
   - the cost sentence, verbatim: "A judge or writer fallback still runs on every Case, also when
     the number is in the band; its reply is not read.";
   - the scope sentence, verbatim: "A sum adds the signals of one member. To compare the panel,
     gate on `"mean:<name>"`.";
   - one `python` code block that assigns `s1_sum_pick` and `s2_band_gate`, each equal to the
     builder of the same fixture (`sum_pick_candidate.url4`, `gate_band_vote_candidate.url4`);
   - the report sentence, verbatim: 'The Case pane, the run summary and the export show the sum
     and the band (see "Combine steps in the report").'.
2. README `### Combine steps in the report`: one new paragraph that starts with
   `**Sums and the band.**` and names the header title `source: sum of 0.5 × sev_a + 0.3 × sev_b`,
   the chip text `gate · agreement >= 0.7 · band [0.6, 0.7] · observed 0.6667 · in band · abstain`,
   the summary line `gate · majority 1 of 3 · fallback 1 of 3 · in band 1 of 3`, and the export key
   `operations[].combine.gate.abstain_band`.
3. CHANGELOG: one bullet at position 3 of the first `### Features` list of `## Unreleased`, that
   starts with `**screamingface:** sum declared signals and abstain in a band (E4b part 6).`,
   holds `the README section "Sum signals and the abstain band"`, and ends with
   `**Requires an SF Engine with the E4b part 6 signal sums and abstain band.**`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **DC-1** Given the README, then `### Sum signals and the abstain band` comes directly after the
  `### Fusion as a named recipe` section and directly before `## Install`, it holds the phrases of
  §2.1, and its one code block compiles to the two fixtures. [proposed]
- **DC-2** Given the CHANGELOG, then exactly one bullet holds `E4b part 6`, and it is bullet 3 of
  the first `### Features` list. [proposed]

### 3.2 Error paths

None.

### 3.3 Derived scenarios

- **DC-D1** (M×M) [proposed] Given `### Combine steps in the report`, then it holds
  `**Sums and the band.**` and `operations[].combine.gate.abstain_band`, and the headings between
  Browse and Accounting are still `[_BROWSE, _COMBINE]`.
- **DC-D2** (M×M) [existing] Given the part 6 bullet, then it holds none of the counted tokens and
  none of `E4b part 3`, `E4b part 4`, `E4b part 5`, so every existing docs test keeps its count and
  its pick.

## 4. Non-functional requirements

- Plain words. The README prose follows the house style of the part 3 to part 5 sections.

## 5. Out of scope

- A README section for part 7 (`consistency@N`): its own part.

## 6. Open questions

None.

## 7. TDD plan

New test file: `ST/test_sum_band_docs.py`. It imports `_section` from
`test_evidence_completeness_docs`, the helpers of `test_show_signals_docs` (as
`ST/test_gate_docs.py:18-25` does), and the two builders from `test_sum_contract_fixtures`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `readme_keeps_its_anchors` (each of `### Signal sources`, `### Gate the majority`, `### Fusion as a named recipe`, `## Install`, `### Browse completed Case results`, `### Combine steps in the report`, `### Completed accounting breakdown` once, in this order) | unit | — | M×M | passes today |
| 2 | `readme_sum_section_sits_after_fusion_and_states_the_rules` (the §2.1 phrases, `in_band`, `abstain_band=(lo, hi)`, `"mean:<name>"`) | unit | DC-1 | M×M | README |
| 3 | `readme_sum_recipes_compile_to_the_fixtures` | unit | DC-1 | H×M | README code block |
| 4 | `combine_report_section_names_sums_and_the_band` | unit | DC-D1 | M×L | README paragraph |
| 5 | `changelog_has_one_part_6_bullet_at_position_3_without_counted_tokens` | unit | DC-2, DC-D2 | M×M | CHANGELOG |

# PRD: README and CHANGELOG for the gate

**Source:** ans:Q1–Q4 (the user writes and reads the gate) · **Priority:** P2
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: `packages/screamingface/README.md`, `packages/screamingface/CHANGELOG.md`

## 1. Summary and user story

As a benchmark author who reads the SDK README, I want one section that shows how to gate a
majority vote, what each fallback does, what it costs today, and how the report shows the gate, so
that I can copy a recipe that the Engine tests prove.

## 2. Background and constraints

- README headings (on `4e622af75`): `### Signal sources` (line 930), then `### Fusion as a named
  recipe` (line 1048); `### Browse completed Case results` (1334), `### Combine steps in the report`
  (1363), `### Completed accounting breakdown` (1393). [existing]
- `ST/test_signal_recipes_readme.py` reads the `### Signal sources` section up to the next `##` or
  `###` heading and runs its code blocks. A new heading right after that section ends it there, so
  that test is not changed. [existing ST/test_signal_recipes_readme.py:25-56]
- `ST/test_show_signals_docs.py:67-72` pins the headings between Browse and Accounting
  (`[_BROWSE, _COMBINE]`): no new heading may go there. A new paragraph inside
  `### Combine steps in the report` is allowed (its test checks phrases only, :75-91). [existing]
- `ST/test_show_signals_docs.py:102-110` pins the FIRST `### Features` list of `## Unreleased`:
  bullet 0 is the part 4 bullet, bullet 1 is the part 3 bullet. The part 5 bullet therefore goes at
  position 2 of that list. [existing]
- The part 5 bullet must hold none of the tokens that other docs tests count:
  `` `output_missing` ``, `` `sf.Pick( ``, `` `sf.Mean( ``, `` `no_weight` ``,
  `` `sf.report.CombineCut` ``, `` `judge_operation_id` ``, `` `sf.JudgeWriterWarning` ``, and the
  text `E4b part 4`. [existing ST/test_show_signals_docs.py:24-35]

### 2.1 Current behavior

No README text and no CHANGELOG bullet name `sf.Gate`, `gate_not_met` or `verify=`.

**Delta.**

1. README: a new section `### Gate the majority` between `### Signal sources` and
   `### Fusion as a named recipe`. It holds, in this order:
   - one paragraph: what a gate is (a comparison of one named number against one threshold, data
     and not code), the three `observe` forms (`agreement`, `chosen:<name>`, `mean:<name>`), the four
     comparisons and the rule "`>=` keeps the majority at equality", the agreement rule (`>=` or
     `>`, a threshold from 0 to 1; the winner's share of the votes, the weight share for a weighted
     vote);
   - one list of the three fallbacks: `otherwise="abstain"` (the Case abstains with `gate_not_met`,
     and coverage counts it with the other abstains); `otherwise=sf.Judge(..., returns="label")` (the
     judge names one member and the answer is that member's text); `otherwise=sf.Model(...)` (the
     model writes the answer);
   - the cost sentence, verbatim: "In this version the fallback call runs on every Case, also when
     the gate keeps the majority, and you pay for it. The gate chooses and records; a cascade that
     skips the call comes with E4c.";
   - the failure sentence, verbatim (contracts C2): "If the fallback call fails, the Case fails,
     also when the gate keeps the majority.";
   - the missing-number rule: no number to compare takes the fallback; a vote with no answer does
     not run the gate and abstains with `no_votes`;
   - one `python` code block that assigns the four recipes `g1_agreement_abstain`,
     `g2_agreement_judge`, `g3_agreement_writer` and `g4_confidence_gate`, each equal to the builder
     of the same fixture in `ST/test_gate_contract_fixtures.py` (GA-D6);
   - one sentence for the logprob cascade: declare `signals={"lp": sf.Logprob("prob")}` and gate on
     `"chosen:lp"`;
   - the verifier sentence: "`sf.Vote(verify=None)` is a reserved place for a later verifier; any
     other value raises `ValueError`.";
   - the name sentence: "This gate is not the per-round gate of a corrective loop.";
   - one sentence that points to the report: "The Case pane, the run summary and the export show
     the gate (see "Combine steps in the report").".
2. README `### Combine steps in the report`: one new paragraph that starts with `**The gate.**` and
   names the chip text `gate · agreement >= 0.7 · observed 0.6667 · fallback · judge`, the
   summary line `gate · majority 2 of 3 · fallback 1 of 3`, and the export key
   `operations[].combine.gate`.
3. CHANGELOG: one bullet at position 2 of the first `### Features` list of `## Unreleased`, that
   starts with `**screamingface:** gate a majority vote (E4b part 5).` and ends with
   `**Requires an SF Engine with the E4b part 5 combine gate.**`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **DC-1** Given the README, then `### Gate the majority` comes directly after the
  `### Signal sources` section and directly before `### Fusion as a named recipe`, and its code
  block compiles to the four gate fixtures. [proposed]
- **DC-2** Given the CHANGELOG, then exactly one bullet holds `E4b part 5`, and it is bullet 2 of the
  first `### Features` list. [proposed]

### 3.2 Error paths

None.

### 3.3 Derived scenarios

- **DC-D1** (M×M) [proposed] Given the `### Combine steps in the report` section, then it holds
  `**The gate.**`, `operations[].combine.gate`, and the headings between Browse and Accounting are
  still `[_BROWSE, _COMBINE]`.
- **DC-D2** (M×M) [existing] Given the part 5 bullet, then it holds none of the counted tokens, so
  every existing docs test keeps its count and its pick.

## 4. Non-functional requirements

- Plain words. The README prose follows the house style of the part 3 and part 4 sections.

## 5. Out of scope

- An E4c README section.

## 6. Open questions

None.

## 7. TDD plan

New test file: `ST/test_gate_docs.py`. It imports `_section` from `test_evidence_completeness_docs`
(the part 4 precedent) and the four builders from `test_gate_contract_fixtures`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `readme_keeps_the_signal_sources_and_report_anchors` (each of the five headings of §2 once, in order) | unit | — | M×M | passes today |
| 2 | `readme_gate_section_sits_after_signal_sources_and_states_the_rules` (phrases: `gate_not_met`, `chosen:<name>`, `mean:<name>`, `>=`, the cost sentence, the failure sentence "If the fallback call fails, the Case fails, also when the gate keeps the majority.", `E4c`, `no_votes`, `verify=None`, `returns="label"`, `corrective loop`) | unit | DC-1 | M×M | README |
| 3 | `readme_gate_recipes_compile_to_the_gate_fixtures` | unit | DC-1 | H×M | README code block |
| 4 | `combine_report_section_names_the_gate` | unit | DC-D1 | M×L | README paragraph |
| 5 | `changelog_has_one_part_5_bullet_at_position_2_without_counted_tokens` | unit | DC-2, DC-D2 | M×M | CHANGELOG |

# PRD: The stage after a Rank or Filter sees the Case input

**Source:** prompt (S7, S9, S10), ans:Q5, ans:Q7, ans:Q13 · **Priority:** P0 (S7, S9 and S10 depend on it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §3, §6](../erd.md) · component: [catalog-and-schema](catalog-and-schema.md)

## 1. Summary and user story

As a benchmark author, I want the model that writes the final answer after a Rank or Filter to see
the Case question, so that it can answer a different question in each Case.

Scenarios from the prompt [stated prompt]:

- **S7** "keep top-N (use only a few of the models answers) -> model synthesizer combines them".
- **S9** "keep >value (use only a few of the models answers) -> model synthesizer combines them".
- **S10** "third party model gives a score to each -> ... -> keep top-N -> model synthesizer
  combines them".

## 2. Background and constraints

- "Always, automatically": the stage after a Rank or Filter always gets the Case input. [stated ans:Q7]
- Rank and Filter only. Concat does not change. [stated ans:Q13]
- "additive edit, no need to care abour versions for now" [stated ans:Q5]. This PRD applies that
  answer to the output of `top_k@1` and `kept@1` too: they change in place, with no `@2`. The code
  rule says a behavior change is a new `@version` [existing E/combine/ports.py:25-27]
  [existing E/combine/operators/selection.py:21-22]. This reading of ans:Q5 is listed in overview
  §6 (P4) for the user to confirm.

### 2.1 Current behavior

- A Rank or Filter Fusion outputs `{"selected":[{"id","text"}]}`.
  [existing E/combine/operators/selection.py:49-52]
- The next Pipeline stage gets only that text as its context. Each later stage receives only the
  previous stage's answer. [existing S/_evaluation/candidate.py:664-681]
- The README says: "No original input or accumulated history is injected implicitly"
  [existing packages/screamingface/README.md:276-277], "that stage receives the selection and
  nothing else" [existing packages/screamingface/README.md:592-595], and "The next stage does not
  receive the original question or the other member texts, so put the task in the prompt of that
  stage." [existing packages/screamingface/README.md:657-659]
- Tests pin the writer message and the envelope: `test_rank_keeps_judge_output_and_next_stage_sees_selection_only`
  [existing ET/test_combine_rank_world.py], `ET/test_combine_selection.py:26,74`, and the filter run
  at `ET/test_sdk_candidate_contracts.py:155`.
- The combine context already has `input`, but `CombineInput` does not carry it.
  [existing E/combine/spec.py:209-216] [existing E/combine/ports.py:216]
- The context may be up to 64 MiB, and a combine result may be up to 8 MiB.
  [existing E/combine/endpoint.py:95-97,475]

**Delta (engine).** `CombineInput` gets `input: str | None = None` (a default, so the test helpers
`ET/combine_flow_support.py:72` and `ET/combine_golden_support.py:97` keep working). The endpoint
always sets it from the context. `_selection_text` adds `"input"` when it is not `None`:
`{"input": "<input>", "selected": [...]}`. The SDK compile does not change, so the compiled url4
bytes stay the same. The README lines above, the CHANGELOG (:53, :57) and the pinned tests change.

**Decision record [proposed — gap §per-connection/sync].** Option A (rejected): the SDK compiles
the next stage's context as `{input, selection}`. That changes every selection Pipeline's bytes,
and it puts the selection JSON into the context as an escaped string. Option C (chosen): the engine
adds `input` to the envelope. The writer gets one flat JSON object, and the url4 bytes do not
change. Cost accepted: every url4 user of `/ensemble/combine/v1` with `top_k@1` or `kept@1` now gets
`input` in the output, and a very large input can exceed the 8 MiB result cap (SI-D3).
Reversibility: two-way door while E4a is unreleased. Change when: an author needs a selection
without the input, or a Case input over a few MiB is real. Then add an opt-out arg.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **SI-1** Given a Case input `"What is 6*7?"`, a Rank Fusion that keeps 2 members, and a writer
  Model stage, then the writer's user message is
  `{"input":"What is 6*7?","selected":[{"id":"member_2","text":"..."},{"id":"member_1","text":"..."}]}`.
  [stated ans:Q7]
- **SI-2** Given a Filter Fusion and a writer stage, then the writer gets the same envelope shape,
  with the kept members in author order. [stated ans:Q7]
- **SI-3** Given a Concat Fusion and a next stage, then the next stage gets the joined text with no
  change. [stated ans:Q13]
- **SI-4** Given any selection Pipeline, then the compiled url4 is byte-identical to today. [proposed]

### 3.2 Error paths

- **SI-E1** Given a Rank that abstains (`cut_not_met`), then there is no envelope, and the Case
  abstains as today. [existing E/combine/operators/selection.py:86-89]
- **SI-E2** Given an envelope over `MAX_RESULT_BYTES` (8 MiB), then the combine call fails with the
  same code as any oversized result today. It does not truncate the input. [existing E/combine/endpoint.py:475]

### 3.3 Derived scenarios (risk-ordered)

- **SI-D1** (H×M) [implied] Given a conversation Case (the input is a candidate-input JSON
  envelope), then `input` holds that JSON text as a string. The writer sees the conversation as
  JSON text. [existing E/world/connector.py:1494-1505]
- **SI-D2** (H×M) [implied] Given a Fusion that is not the first Pipeline stage, then `input` is the
  input of that Fusion (the previous stage's output), not the Case question. The README says so.
  (Scope note; see overview §7.)
- **SI-D3** (M×L) [implied] Given a Case input of more than about 8 MiB minus the kept texts, then
  SI-E2 applies. Benchmark inputs today are far smaller.
- **SI-D4** (M×M) [proposed] Given a Case input with quotes, newlines or non-ASCII text, then the
  envelope is valid canonical JSON (`ensure_ascii=False`) and round-trips the input exactly.
  [existing E/combine/ports.py:540-544]
- **SI-D5** (M×L) [implied] Given a stage after the selection that is a Fusion or a Recipe, not a
  Model, then it gets the same envelope as its context.
- **SI-D6** (L×L) [implied] Given member texts that contain prompt-injection text, then nothing
  changes. Member texts already reach the writer today. The Case input is the same trust level as
  the members' own input.

## 4. Non-functional requirements

- Output size grows by the input length, once, inside the 8 MiB cap. [existing E/combine/endpoint.py:97]
- No change to cost or call count. [implied]

## 5. Out of scope

- Concat. [stated ans:Q13]
- An opt-out arg. [stated ans:Q7]
- Giving the input to stages after a non-selection stage. [existing packages/screamingface/README.md:276-277]

## 6. Open questions

None.

## 7. TDD plan

Order: core-out (engine envelope, then the world-level writer message, then docs).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `concat_output_is_the_joined_text` | unit | SI-3 | M×M | passes today |
| 2 | CHAR `selection_pipeline_url4_bytes_are_unchanged` (readme-514-ranked, filter_pipeline) | unit | SI-4 | H×M | passes today and after |
| 3 | `top_k_envelope_has_the_input_and_the_selected_members` | unit | SI-1 | H×H | `_selection_text(chosen, combine_input)` adds `input` |
| 4 | `kept_envelope_has_the_input_and_the_kept_members` | unit | SI-2 | H×H | same helper; approved edit of `test_combine_selection.py:26,74` |
| 5 | `combine_input_carries_the_context_input_verbatim` | unit | CI-I1 | H×M | set in the endpoint where `CombineInput` is built |
| 6 | `envelope_round_trips_unicode_quotes_and_newlines` | unit | SI-D4 | M×M | canonical_json |
| 7 | `rank_world_writer_sees_the_input_and_the_selection` (replaces the "selection only" test) | integration | SI-1 | H×H | approved edit of a pinned test |
| 8 | `filter_pipeline_writer_sees_the_input_and_kept_members` | integration | SI-2 | H×M | approved edit of `test_sdk_candidate_contracts.py:155` |
| 9 | `envelope_input_is_the_fusion_input_in_a_later_stage` | integration | SI-D2 | H×M | no special case |
| 10 | `conversation_input_appears_as_json_text_in_the_envelope` | unit | SI-D1 | M×M | no special case |
| 11 | `oversized_envelope_fails_like_any_oversized_result` | unit | SI-E2, SI-D3 | M×L | no change; pins the cap |
| 12 | `selection_feeding_a_fusion_stage_gets_the_envelope` | integration | SI-D5 | M×L | no change |
| 13 | `rank_cut_not_met_abstains_without_an_envelope` | unit | SI-E1 | M×L | no change |

SI-D6 has no test: it adds no new trust boundary. See test-plan §5.

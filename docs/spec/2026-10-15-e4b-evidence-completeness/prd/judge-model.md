# PRD: The judge model in the evidence (`judge_model`)

**Source:** ans:Q1, ans:Q2 (epic OME-1290 gap E2) · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §3, §4](../erd.md) · component: [evidence-schema](evidence-schema.md) ·
related: [judge-writer-warning](judge-writer-warning.md)

## 1. Summary and user story

As a researcher who reads the evidence of a judge step, I want the evidence to name the judge
model, so that I can check that the model that scored the members is not the model that wrote the
answer after the cut.

## 2. Background and constraints

- Epic OME-1290 behavior 3: "The writing model is a later stage. It is not allowed to be the thing
  that also computed the score." The roadmap answer: "Record ids + warn". [stated ans:Q1]
- "Judge id + SDK warning": the combine evidence records the judge model; the writer's model
  stays on its own operation record; the SDK warns at compile time when the two are the same.
  [stated ans:Q2]

### 2.1 Current behavior

- The judge is a model call that the SDK compiles next to the combine call. The combine call gets
  only its reply text, as `context.signals["judge"]`. [existing S/judge.py:190-204]
  [existing E/combine/spec.py:210-220]
- The engine reads the reply as a label or as scores (`score:judge`). It never sees the judge
  route. [existing E/combine/endpoint.py:244-249]
- The combine route has the request params, context and intent only. It cannot tell which recorded
  call made the judge reply. [existing E/world/combine.py:52-74]
- `JudgeReadingRecord` exists only for the `judge` reducer. A Rank, Filter or Vote that reads
  `score:judge` writes `judge: null`. [existing E/combine/evidence.py:94-99]
  [existing E/combine/endpoint.py:600]
- The SDK builds the spec from the reducer plan, with sorted keys. [existing S/_evaluation/combine_spec.py:43-77]

**Delta.**

1. SDK: `combine_spec_text` adds `"judge_model": <route>` when the reducer plan has a model call
   with key `"judge"`. The route is the string the url4 judge call uses. [stated ans:Q2]
2. Engine: `CombineSpec.judge_model: str | None = None` (optional key). The endpoint refuses it
   when the step reads no judge (CS-I2). [proposed]
3. Engine: `CombineEvidence.judge_model` (optional key) copies the spec value.
   [stated ans:Q2]

**Design note.** The brief proposed `JudgeReadingRecord.model`. That record exists only for the
`judge` reducer, so a Rank, Filter or Vote by judge score would still have no model. A top-level
optional key covers all four judge uses. [proposed]

**Cost (an implied consequence of ans:Q2).** The engine can learn the route only from the SDK, so
the compiled url4 of every judge recipe changes. Seven contract fixtures and the SDK tests that
pin a judge spec's bytes need owner-approved edits (plan §6). A url4 compiled before part 2 still
runs, without `judge_model` in its evidence. See §6.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **JM-1** Given `sf.Fusion(..., synthesizer=sf.Judge("openrouter/x/y", returns="scores", ...))`,
  then the compiled spec has `"judge_model": "<the url4 route of that judge call>"`, and the step's
  evidence has the same `judge_model`. [stated ans:Q2]
- **JM-2** Given `sf.Rank(2, by=sf.Judge(...))`, `sf.Filter(where=sf.signal("score:judge") >= 7,
  judge=...)`, or `sf.Vote(weights=sf.signal("score:judge"), judge=...)`, then the spec and the
  evidence carry `judge_model` too. [stated ans:Q2]
- **JM-3** Given a reducer with no judge, then the compiled spec has no `judge_model` key, and its
  bytes equal the bytes before part 2. [implied]

### 3.2 Error paths

- **JM-E1** Given a spec with `judge_model` and a reducer that reads no judge, then the call fails
  with `combine_spec_invalid`. [proposed]
- **JM-E2** Given a judge spec without `judge_model` (compiled before part 2), then the call runs as
  today, and the evidence has no `judge_model` key. [proposed]
- **JM-E3** Given `judge_model` that is empty, longer than 256 characters, not a string, or has a
  control character, then the call fails with `combine_spec_invalid`. [proposed — gap §security]

### 3.3 Derived scenarios (risk-ordered)

- **JM-D1** (H×M) [implied] Given each judge recipe of the contract fixtures, then the SDK compile
  and the regenerated fixture are byte-equal (the fixture drift guard).
- **JM-D2** (M×M) [proposed] Given `judge_model`, then the engine never logs it and never uses it to
  route a call. It is display data only (CS-I3).
- **JM-D3** (M×L) [implied] Given a merge reducer with writer calls (`writer_<field>`), then no
  `judge_model` is written: a merge writer is not a judge. [existing S/reducer.py:56-61]
- **JM-D4** (M×L) [implied] Given a corrective loop that recompiles its member Fusion each round,
  then each round's spec has the same `judge_model`.

## 4. Non-functional requirements

- The spec stays under its byte cap. One route adds at most 256 bytes.
  [existing S/_evaluation/combine_spec.py:74-76]
- No new I/O in the combine core. [existing E/combine/ports.py:3]

## 5. Out of scope

- The writer model in the combine evidence (a cross-stage link). [stated ans:Q2]
- The judge's params or rubric in the evidence. [proposed]

## 6. Open questions

1. **Emerged after the decision round: the url4 bytes of judge recipes change.** Default: accept,
   as answered in ans:Q2. The other option is no wire change: the SDK case view links each combine
   step to the judge's own operation record, which already holds the route. That option changes no
   fixture, but the evidence alone would not name the judge. I would keep the default, because the
   epic asks the report to show the scorer, and E4b is not released.

## 7. TDD plan

Order: characterize the non-judge spec bytes, then the SDK key, then the engine spec and evidence.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `non_judge_spec_bytes_do_not_change` | unit | JM-3 | H×M | passes today |
| 2 | `judge_reducer_spec_names_the_judge_model` | unit | JM-1 | H×M | `combine_spec_text` reads the `"judge"` model call |
| 3 | `rank_filter_and_vote_by_judge_name_the_judge_model` | unit | JM-2 | H×M | same rule |
| 4 | `merge_writer_calls_add_no_judge_model` | unit | JM-D3 | M×L | key `"judge"` only |
| 5 | `engine_copies_judge_model_into_the_evidence` | unit | JM-1 | H×M | `CombineSpec.judge_model`, `_evidence` |
| 6 | `judge_model_without_a_judge_read_is_spec_invalid` | unit | JM-E1 | M×M | check in `_plan` |
| 7 | `judge_spec_without_judge_model_still_runs` | unit | JM-E2 | H×M | optional key |
| 8 | `judge_model_text_is_checked_by_the_engine` | unit | JM-E3 | M×M | ES#8 rule |
| 9 | `engine_does_not_log_the_judge_model` | unit | JM-D2 | M×M | caplog over a judge run |
| 10 | `judge_fixtures_match_the_sdk_compile` | unit | JM-D1 | H×M | regenerate 7 fixtures (approved) |
| 11 | `corrective_rounds_keep_the_judge_model` | unit | JM-D4 | M×L | — |
| 12 | `engine_runs_a_judge_rank_and_reports_the_model` | integration | JM-2 | H×M | `run_candidate` on `recipe_s10.url4` |

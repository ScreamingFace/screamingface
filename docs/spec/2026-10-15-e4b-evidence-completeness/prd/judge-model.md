# PRD: The judge model in the SDK view (a link to the judge's own operation)

**Source:** ans:Q1, ans:Q2, ans:Q4 (epic OME-1290 gap E2) · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: related: [judge-writer-warning](judge-writer-warning.md)

## 1. Summary and user story

As a researcher who reads the trace of a judge step, I want the trace to name the judge model next
to the combine step, so that I can check that the model that scored the members is not the model
that wrote the answer after the cut.

## 2. Background and constraints

- Epic OME-1290 behavior 3: "The writing model is a later stage. It is not allowed to be the thing
  that also computed the score." [stated prompt] The roadmap answer: "Record ids + warn".
  [stated ans:Q1]
- "Judge id + SDK warning": the judge id is recorded; the writer's model stays on its own operation
  record; the SDK warns at compile time when the two are the same. [stated ans:Q2]
- "No wire change, SDK link": no `judge_model` key in the combine spec or in the engine evidence.
  The SDK view links the combine step to the judge's own operation record, which already holds the
  model. The owner accepts this SDK view as "the evidence" for the judge id, so ans:Q2 is met
  through the view. [stated ans:Q4]

### 2.1 Current behavior

- The SDK compiles each judge as its own model call, with its own operation `op_<binding>`. The
  operation kind is `"judge"`. [existing S/_evaluation/reducer_signals.py:213-251]
  [existing S/_evaluation/topology.py:91-107]
- The url4 replay (a Candidate rebuilt from url4) gives the same operation kinds, through the same
  `_operation_shape` rule. [existing S/_evaluation/url4.py:301-313]
- The combine operation depends on its members first, then on its signal calls (the judge among
  them). [existing S/_case_views.py:213-226] [implied]
- Each model-call operation of a Case carries its accounting, and the trace `model_call` entry shows
  `model` from `accounting.request_model`. So the judge's own record already holds the model.
  [existing S/_case_views.py:180-200]
- The trace `reduce` entry has a fixed field set, pinned by `TRACE_FIELDS` and
  `report-trace.v1`. It does not name the judge. [existing S/report_trace.py:18-40]
  [existing ST/data/schemas/screamingface.report-trace.v1.json]
- A step reads a judge in three ways, and E4a pairs each with exactly one `"judge"` model call:
  the `judge` reducer (`label@1` or `scores@1`); a reduce step `scores@1` with `source="judge"`
  (Rank by judge); and a signal read of `score:judge` (Vote, Filter or Pick by judge score).
  [existing E/combine/operators/judge.py:70-85] [existing E/combine/endpoint.py:381-397]
  [existing S/reducer.py:329-370]

**Delta.** The trace `reduce` entry gets two keys, `judge_operation_id` and `judge_model`. The SDK
fills them from the graph and the Case. The combine spec, the engine, the evidence wire and every
url4 file do not change. [stated ans:Q4]

**Rule [proposed] (the "reads a judge" test on the SDK side, review M1).** A combine step reads a
judge when its evidence shows one of:

| # | Evidence | Engine meaning |
|---|---|---|
| J1 | `reducer == "judge"` | the `judge` reducer |
| J2 | `"scores@1"` in `operators` and `judge` is not null | `scores@1` with `source="judge"` (the `values` source writes no judge reading) [existing E/combine/operators/judge.py:70-79] |
| J3 | `signal.key == "score:judge"` | a signal read of the judge score |

When the rule holds and the step's graph node has exactly one dependency of kind `"judge"`, then
`judge_operation_id` is that operation id, and `judge_model` is that operation's
`accounting.request_model`. In every other case both keys are null.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **JM-1** Given a Fusion with `synthesizer=sf.Judge("openrouter/x/y", returns="scores", ...)`,
  then the trace `reduce` entry of its combine step has `judge_operation_id` equal to the judge
  call's operation id, and `judge_model` equal to the `model` of that operation's `model_call`
  entry. [stated ans:Q2] [stated ans:Q4]
- **JM-2** Given `sf.Rank(2, by=sf.Judge(...))`, `sf.Filter(where=sf.signal("score:judge") >= 7,
  judge=...)`, or `sf.Vote(weights=sf.signal("score:judge"), judge=...)`, then the `reduce` entry
  links the judge in the same way (J2, J3). [stated ans:Q2]
- **JM-3** Given a step that reads no judge, then both keys are null. [implied]
- **JM-4** Given any Candidate, then its compiled url4 is byte-equal to the url4 before part 2.
  [stated ans:Q4]

### 3.2 Error paths

- **JM-E1** Given a judge operation with no accounting (an unattributed call), then
  `judge_operation_id` is set and `judge_model` is null. The view never guesses. [proposed]
- **JM-E2** Given a Case with no bound operation graph (an old result), then both keys are null.
  [existing S/_case_views.py:68-72] [proposed]
- **JM-E3** Given the rule holds but the node has zero or several `"judge"` dependencies, then both
  keys are null. [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **JM-D1** (H×M) [stated ans:Q4] Given a judge url4 compiled before part 2, then it still
  rebuilds, runs, and its trace links the judge (the url4 replay gives the same operation kinds).
- **JM-D2** (M×M) [implied] Given `scores@1` with `source="values"` (Rank by a numeric field), then
  J2 does not hold (no judge reading) and both keys are null.
- **JM-D3** (M×L) [implied] Given a merge reducer with writer calls (`writer_<field>`), then no
  judge is linked: a writer call has the kind `"writer"`. [existing S/_evaluation/topology.py:99-100]
- **JM-D4** (M×L) [implied] Given a quorum panel that abstains with no member, so the judge
  reading is null, then J2 fails and the keys are null, unless J1 or J3 holds.

## 4. Non-functional requirements

- No network call: the view reads the Case and its bound graph only.
  [existing S/_case_views.py:3]
- The new keys change the `report-trace.v1` field set of the `reduce` kind (an owner-approved
  edit). [proposed]

## 5. Out of scope

- A `judge_model` key in the combine spec or in the engine evidence. [stated ans:Q4]
- The writer model in the combine step's view (the writer's own `model_call` entry shows it).
  [stated ans:Q2]
- The judge's params or rubric in the view. [proposed]

## 6. Open questions

None. (The 2026-10-15 re-ask settled the wire question: ans:Q4.)

## 7. TDD plan

Order: characterize the url4 bytes and the judge `model_call` entry, then add the link.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `judge_recipe_url4_bytes_do_not_change` | unit | JM-4 | H×M | passes today; the fixture drift guard stays green |
| 2 | CHAR `judge_call_model_call_entry_shows_its_model` | unit | [existing S/_case_views.py:180-200] | H×M | passes today |
| 3 | `judge_reducer_trace_links_the_judge_operation_and_model` | unit | JM-1 | H×M | J1, unique `"judge"` dependency |
| 4 | `rank_filter_and_vote_by_judge_link_the_judge` | unit | JM-2 | H×M | J2, J3 |
| 5 | `step_without_a_judge_has_null_judge_keys` | unit | JM-3 | H×M | — |
| 6 | `unattributed_judge_call_gives_null_model` | unit | JM-E1 | M×M | — |
| 7 | `case_without_graph_gives_null_judge_keys` | unit | JM-E2 | M×M | — |
| 8 | `zero_or_two_judge_dependencies_give_null_keys` | unit | JM-E3 | M×L | — |
| 9 | `old_judge_url4_rebuilds_and_links_the_judge` | integration | JM-D1 | H×M | url4 replay path |
| 10 | `values_scores_rank_links_no_judge` | unit | JM-D2 | M×M | J2 needs the judge reading |
| 11 | `merge_writer_is_not_linked_as_judge` | unit | JM-D3 | M×L | kind `"writer"` |
| 12 | `trace_reduce_field_set_matches_report_trace_v1` | unit | §4 | H×M | `TRACE_FIELDS`; approved snapshot edit |

# PRD: Warn when the writer uses the judge's model (`JudgeWriterWarning`)

**Source:** ans:Q1, ans:Q2, ans:Q4 (epic OME-1290 gap E2) · **Priority:** P2
**Lifecycle:** planned
**Owner:** unassigned
Paths: related: [judge-model](judge-model.md)

## 1. Summary and user story

As a researcher who builds `Pipeline([Fusion(... judge ...), writer])`, I want a warning when the
writer stage uses the same model as the judge, so that I know the epic rule "the writer is not the
scorer" is broken before I spend money on the run.

## 2. Background and constraints

- "Record ids + warn": warn, do not fail. One strong model in two roles is a legitimate recipe.
  [stated ans:Q1]
- The SDK warns at compile time. The combine step never sees the writer's model. [stated ans:Q2]
- The warning stays as specced after the re-ask; only the recorded judge id moved to the SDK view
  ([judge-model](judge-model.md)). [stated ans:Q4]
- The SDK already has a compile-time warning for a reducer Fusion:
  `DuplicateMembersWarning(EvaluationWarning)`, sent once per Fusion object with
  `skip_file_prefixes=(SDK_PACKAGE_ROOT,)`. [existing S/warnings.py:4-16]
  [existing S/_evaluation/candidate.py:587-590,799-830]
- The candidate rebuild from url4 silences `DuplicateMembersWarning`, because the researcher heard
  it at the first compile. [existing S/url4.py:432-442]
- The Pipeline compile walks the stages in order, and each stage's context is the previous stage's
  output. [existing S/_evaluation/candidate.py:660-688]
- A judge is a reducer model call with key `"judge"`, and `sf.Judge.model` holds its route.
  [existing S/reducer.py:53-61] [existing S/judge.py:180-196]

## 3. Scenarios and acceptance criteria

**Rule [proposed].** For each pair of adjacent stages (A, B) of a Pipeline: when A is a Fusion
that reads a judge, and B is a direct `sf.Model` stage (or a route string), and
`_canonical_model(B.model) == _canonical_model(J.model)` where J is A's `"judge"` model call, the
compile sends one `JudgeWriterWarning`. The message names the Pipeline, the two stage positions and
the canonical route. It holds no prompt, rubric or member text.

- **"Reads a judge" (review M1).** The engine reads a judge in three ways: the `judge` reducer; a
  reduce step `scores@1` with `source="judge"` (Rank by judge); a signal read of `score:judge`
  (Vote, Filter, Pick by judge score). In the SDK, E4a pairs each of the three with exactly one
  reducer model call whose key is `"judge"`, and no other reducer has one. So the SDK test is: the
  reducer plan has a `_ModelSignal` with key `"judge"`. [existing S/reducer.py:53-61,329-370]
  [existing E/combine/operators/judge.py:70-85] The SDK view uses the same three cases, read from
  the evidence ([judge-model](judge-model.md) J1–J3).
- **Canonical form (review M2).** Both sides go through `_canonical_model`, the form the duplicate
  check uses. The url4 call path is `"/" + model`, so the warning never compares a path with a
  model id. [existing S/_evaluation/candidate.py:812-818,868-881]

### 3.1 Happy path

- **JW-1** Given `sf.Pipeline([sf.Fusion([...], synthesizer=sf.Rank(2, by=sf.Judge("openrouter/a/b",
  ...))), "openrouter/a/b"])`, then compiling it sends one `JudgeWriterWarning` that names stages 1
  and 2 and `openrouter/a/b`, and the compile succeeds with the same url4 as without the warning.
  [stated ans:Q1] [stated ans:Q2]
- **JW-2** Given the same Pipeline with the writer `"openrouter/c/d"`, then no warning is sent.
  [implied]

### 3.2 Error paths

- **JW-E1** Given the warning is turned into an error by the caller (`warnings.simplefilter("error",
  sf.JudgeWriterWarning)`), then the compile raises it. The SDK itself never raises. [implied]

### 3.3 Derived scenarios (risk-ordered)

- **JW-D1** (H×M) [implied] Given two spellings of one route (for example with and without the
  provider prefix that the SDK adds), then they count as the same model, as in
  `DuplicateMembersWarning`. [existing S/_evaluation/candidate.py:812-818]
- **JW-D2** (M×M) [proposed] Given one Pipeline object compiled twice (for example by a corrective
  loop), then the warning is sent once.
- **JW-D3** (M×M) [proposed] Given the candidate rebuild from url4, then the warning is silenced,
  as `DuplicateMembersWarning` is.
- **JW-D4** (M×L) [proposed] Given a judge Fusion that is the LAST stage, or a judge Fusion followed
  by another Fusion, then no warning is sent (no direct model writer).
- **JW-D5** (M×L) [implied] Given a Vote, Filter or Pick that reads `score:judge` and is followed by
  the judge's model, then the warning is sent too: the rule reads the judge model call, not the
  reducer kind.
- **JW-D6** (L×L) [implied] Given a Fusion with a merge writer (`writer_<field>`), then no warning is
  sent: a merge writer is not a judge.

## 4. Non-functional requirements

- No network call and no catalog read: the check reads the Recipe objects only. [proposed]
- The warning class is public: `sf.JudgeWriterWarning`, a subclass of `sf.EvaluationWarning`. The
  public surface snapshot changes (owner-approved). [proposed]

## 5. Out of scope

- A writer that is a Fusion with a model synthesizer, or a nested Pipeline whose first stage is the
  judge model. [proposed]
- Any engine check: the engine never sees both models. [stated ans:Q2]

## 6. Open questions

None.

## 7. TDD plan

Order: outside-in from the public warning, because the rule is SDK-only.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `judge_then_same_model_writer_warns_once` | unit | JW-1 | H×M | check in `_pipeline`, adjacent pairs |
| 2 | `warning_does_not_change_the_url4` | unit | JW-1 | H×M | compare url4 with the warning filtered |
| 3 | `different_writer_model_does_not_warn` | unit | JW-2 | H×M | — |
| 4 | `two_spellings_of_one_route_warn` | unit | JW-D1 | H×M | reuse `_canonical_model` |
| 5 | `warning_as_error_raises_from_compile` | unit | JW-E1 | M×L | — |
| 6 | `one_pipeline_compiled_twice_warns_once` | unit | JW-D2 | M×M | `_warned_pipelines` set, as `_warned_fusions` |
| 7 | `url4_rebuild_silences_the_warning` | unit | JW-D3 | M×M | add to the `catch_warnings` block |
| 8 | `judge_as_last_stage_or_before_a_fusion_does_not_warn` | unit | JW-D4 | M×L | — |
| 9 | `vote_and_filter_by_judge_score_warn_too` | unit | JW-D5 | M×L | rule reads the `"judge"` call |
| 10 | `merge_writer_does_not_warn` | unit | JW-D6 | L×L | — |
| 11 | `judge_writer_warning_is_public` | unit | §4 | M×M | export; approved snapshot edit |

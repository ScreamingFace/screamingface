# E4b part 5: gate record and verifier slot — overview

**Status:** draft, written headless from the owner interview of 2026-10-16 (Q1–Q4). Waiting for
owner review. **Epic:** E4b (OME-1290). **Leaf:** filed at PR-open.
**Base:** branch `e4b-show-signals` (E4b part 4, restacked on parts 2 and 3) at `4e622af75`.
Branch `e4b-gate-record`, worktree `.claude/worktrees/e4b-gate-record`.

## 1. Summary

E4a and E4b parts 1–4 give a majority vote, its `agreement` number, declared signals and a report
that shows them. No rule reads `agreement`, and no rule reads a declared signal to choose between
the majority and a second opinion. Epic OME-1290 behavior 4 asks for this: "Compute the agreement
fraction from the panel (winner count / votes) ... If it is at least a threshold, the answer is the
majority member's text ... If it is below, run the fallback: a judge that copies, a writing model,
or an abstain." Behavior 5 asks for "a named place on the vote so a check can be added without a
new join type".

This part adds:

- `sf.Gate(observe, cmp, threshold, *, otherwise="abstain")` on `sf.Vote(gate=...)`. The gate is
  DATA: a comparison of one named number against one threshold. It is never Python code.
  `observe` is `"agreement"`, `"chosen:<name>"` (a declared signal of the chosen member) or
  `"mean:<name>"` (the mean of a declared signal over the members) (ans:Q2).
- Three fallbacks (ans:Q3): `"abstain"` (a scored decline with the new reason `gate_not_met`), an
  `sf.Judge(..., returns="label")` that names a member whose text is copied, and an `sf.Model`
  that writes the answer.
- The gate CHOOSES and RECORDS (ans:Q1). The fallback call still runs and costs money on every
  Case. The combine step picks the majority or the fallback output and writes a `gate` record
  into the evidence: the observed number and its source, the comparison, the threshold, the result
  of the comparison and the branch. E4c (OME-1291) later removes the unused call with no wire
  change.
- The verifier slot (ans:Q4): `sf.Vote(verify=None)` accepts only `None`, with a clear error for
  any other value. The evidence schema reserves an optional key `verifier`.
- The part 4 surfaces show the gate: a chip in the Case pane Combine section, a gate line in the
  run summary, and the record in the JSON export (`operations[].combine.gate`).

Wire changes, all additive in the v1 schemas (no new schema id): the optional combine-spec key
`gate`, the optional evidence keys `gate` and `verifier`, the abstain reason `gate_not_met`, and two
combine-context signal keys `fallback_judge` and `fallback_writer`. No new failure code, no new
combine route, no new operation kind, no new url4 grammar.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`,
`S/` = `packages/screamingface/src/screamingface/`, `ET/` = `apps/screamingface-engine/tests/unit/`,
`ST/` = `packages/screamingface/tests/`. Line numbers are on base `4e622af75`.

**Epic map** (OME-1290 items that this part closes):

| Epic item | Status after this part |
|---|---|
| Behavior 4: agreement fraction against a threshold; majority or fallback (judge, writer, abstain) | done, choose and record ([gate-decision](prd/gate-decision.md), [gate-api](prd/gate-api.md)); the skip is E4c |
| "This epic can compute "0.4 < 0.7" and record it" | done ([gate-record](prd/gate-record.md)) |
| "Abstain is a distinct outcome ... Coverage counts it separately" | done: `gate_not_met` is an abstain result; the Case is `candidate_abstained` through the existing final-operation rule |
| Behavior 5: a named place on the vote for a verifier, no new join type | done as a reserved slot ([verifier-slot](prd/verifier-slot.md)); the check is a later part |
| Part 3 G1: record a logprob against a threshold | done: `chosen:<name>` and `mean:<name>` over a declared `sf.Logprob` |
| Part 4 §8: "E4b part 5 (gates) can show its gate record in the same Combine section" | done ([gate-display](prd/gate-display.md)) |

## 2. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| SDK user API (new `S/gate.py`, `S/reducer.py` `Vote`, `S/fusion.py`, `S/__init__.py`) | `sf.Gate`, `gate=`, `verify=`, the declared-name check | gate-api, verifier-slot |
| SDK compile (`S/_evaluation/combine_spec.py`, `S/_evaluation/reducer_signals.py`, `S/_evaluation/topology.py`) | spec key `gate`, the fallback call, its topology and label | gate-api |
| SDK rebuild (`S/url4.py`, `S/reducer.py` `Vote._rebuild`) | `Url4.to_python` of a gated vote | gate-api |
| SDK evidence (`S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`, `S/answer.py`, `S/report.py`) | `CombineGate`, decoder, `gate_not_met` | gate-record, verifier-slot |
| Engine combine core (`E/combine/spec.py`, `E/combine/ports.py`, `E/combine/evidence.py`, `E/combine/endpoint.py`, new `E/combine/gate.py`) | parse, decide, record | gate-record, gate-decision |
| SDK display (`S/_ui/combine_view.py`, `S/_case_views.py`) | gate chip, summary line, judge link | gate-display |
| Contract data (`ET/data/combine_contract/`, `ST/data/schemas/`) | schema snapshots, evidence cases, url4 fixtures | gate-record, gate-decision, gate-api |
| Docs (`packages/screamingface/README.md`, `CHANGELOG.md`) | user guidance | docs |

## 3. Reading order

1. [erd.md](erd.md)
2. [prd/gate-record.md](prd/gate-record.md) (component, P0)
3. [prd/verifier-slot.md](prd/verifier-slot.md) (P1)
4. [prd/gate-decision.md](prd/gate-decision.md) (P0)
5. [prd/gate-api.md](prd/gate-api.md) (P0)
6. [prd/gate-display.md](prd/gate-display.md) (P1)
7. [prd/docs.md](prd/docs.md) (P2)
8. [contracts.md](contracts.md), [test-plan.md](test-plan.md)

## 4. PRD index

| PRD | Lifecycle | Scenarios (happy / error / derived) | TDD rows |
|---|---|---|---|
| [gate-record](prd/gate-record.md) | existing | 5 / 4 / 6 | 14 |
| [verifier-slot](prd/verifier-slot.md) | planned | 3 / 2 / 2 | 6 |
| [gate-decision](prd/gate-decision.md) | existing | 8 / 5 / 10 | 20 |
| [gate-api](prd/gate-api.md) | existing | 6 / 4 / 9 | 20 |
| [gate-display](prd/gate-display.md) | existing | 5 / 1 / 5 | 12 |
| [docs](prd/docs.md) | existing | 2 / 0 / 2 | 5 |
| **Total** | | **29 / 16 / 34** | **77** |

## 5. Interview ledger

The prompt is the E4b roadmap ("Part 5. Gate record and verifier slot", DB-5 of 2026-10-15) and the
owner brief of 2026-10-16. The owner answered four questions (multiple choice). The answers are
verbatim option labels. Do not ask them again.

| Id | Question | Answer | Note |
|---|---|---|---|
| Q1 | What does the gate do in E4b? | "Chooses + records (Recommended)" | The fallback still runs (cost spent). The gate picks the majority answer or the fallback answer, and records the comparison and the branch. E4c (OME-1291) later removes the unused call with no wire change. |
| Q2 | Which numbers can the gate read? (multi) | "Agreement (Recommended)", "Chosen member's signal", "Mean over members" | Agreement = winner count / votes, computed (already in the evidence as `agreement`). A declared signal (part 3) of the chosen member, for example a logprob `prob` or a verbalized confidence (the logprob-cascade case). The mean of a declared signal over the panel. |
| Q3 | Which fallbacks? (multi) | "Abstain (Recommended)", "Judge that copies", "Writing model" | Below the threshold: a scored decline with its own reason; or the existing `sf.Judge` picks among the members; or the existing model synthesizer writes the answer. |
| Q4 | The verifier slot? | "Reserved param + key (Recommended)" | The vote gets `verify=`, which accepts only None now (clear error otherwise). The evidence schema reserves an optional `verifier` key. A later part adds the check with no new join type. |

Epic text that sets the scope (OME-1290 behavior 4, verbatim): "The fraction is computed, not asked
of a model." "The threshold is a number in the recipe." "Abstain is a distinct outcome, not an
empty string that looks like a wrong answer. Coverage counts it separately."

E4c text that the wire must serve (OME-1291, verbatim): "The condition is a comparison the author
wrote against a declared signal: `confidence < 0.7`, `agreement < 0.8`. It is data. It is not a
Python function ... nobody else could replay it." "The report shows every stage that ran, the
signal value, the comparison, and the stages that did not run." "`fail_closed` versus abstain.
Abstain is a scored decline. Fail-closed is an error. They must not share a status code."

## 6. Global decisions [proposed]

Each item below is an engineering decision made without the owner, from the answers above. The
owner approves or changes them at review (plan §6).

| # | Decision | Where |
|---|---|---|
| P1 | **Where the gate lives.** On `sf.Vote` only, as `sf.Vote(..., gate=sf.Gate(...))`. In the url4 it is the optional top-level key `gate` of the vote's combine spec (`screamingface.combine-spec.v1`), next to `signals`. A spec with `gate` and a reducer other than `vote` is refused. WHY: ans:Q2 names the vote's agreement; one place keeps the rule small. Other reducers are deferred (D3). | [erd §1](erd.md), [gate-api](prd/gate-api.md) |
| P2 | **The name `gate`.** The public names are `sf.Gate` and the evidence key `gate`. The corrective loop has an internal route `/ensemble/corrective/v1/gate` (S/_evaluation/corrective.py:57, E/benchmarks/ensemble/policy.py:23). That is a different concept (a per-round check of a corrective loop), it is not public API, and this part does not change it. The README says so in one sentence. | [docs](prd/docs.md) |
| P3 | **The gate is data.** `sf.Gate(observe, cmp, threshold, *, otherwise="abstain")`. `observe` is text: `"agreement"`, `"chosen:<name>"` or `"mean:<name>"`, where `<name>` is a name that the Fusion declares (part 3). An E4a key (`cost_usd`, `score:judge`, `field:<path>`) is refused (ans:Q2: "a declared signal"). The spec holds `{"cmp", "observe", "otherwise", "threshold"}`, so E4c can read the same object to skip a branch. | [erd §1](erd.md), C1 |
| P4 | **The comparison is the PASS condition.** `cmp` is one of `>=`, `>`, `<=`, `<`. When `observed cmp threshold` is true, the gate passes and the answer is the majority. For `agreement`, only `>=` and `>` are allowed, and the threshold is in `[0, 1]`. `>=` takes the majority at equality (the epic: "at least a threshold"). A declared signal takes any finite threshold and any of the four comparisons (an entropy uses `<=`). | [gate-decision](prd/gate-decision.md) §2 |
| P5 | **How a fallback runs (ans:Q1).** A judge or writer fallback is ONE extra model call that the vote's combine step reads, the same way a judge-weighted vote reads its judge today (`_ModelSignal`, S/reducer.py:52-62). Its reply reaches the combine call as `context.signals["fallback_judge"]` or `context.signals["fallback_writer"]`. The call reads the Fusion context (the question and the members, or the quorum panel), as the judge and the model synthesizer do. No new route, no new combine call, no new operation kind (`judge` and `writer` exist). | [erd §2–3](erd.md), C2 |
| P6 | **Judge fallback.** `sf.Judge(model, returns="label", rubric=...)` only, with the existing label template (`judge-template@1 returns=label`). The Engine parses the reply with `parse_label` over the members that answered (E/combine/operators/judge.py:47-58), and the answer is that member's text, byte for byte. A `returns="scores"` judge is refused with a clear message (D2). | [gate-decision](prd/gate-decision.md) GD-3 |
| P7 | **Writer fallback.** `sf.Model(model, prompt=..., params=...)` without `name=` and without `optional=True` (neither can round-trip through the url4 of a signal call). The prompt default is `DEFAULT_SYNTHESIS_PROMPT`, as for a model synthesizer (S/_evaluation/candidate.py:502). The reply is the answer, verbatim (a built result). | [gate-decision](prd/gate-decision.md) GD-4 |
| P8 | **FB-I1: the fallback reply is read only on the fallback branch.** On the majority branch the Engine never reads `fallback_judge` or `fallback_writer`: a missing or bad reply there changes nothing. So the evidence of a passed gate is the same bytes whether the fallback call ran (E4b) or not (E4c). This is the property that lets E4c add the skip with no wire change. | [gate-decision](prd/gate-decision.md) GD-8, C8 |
| P9 | **Evidence gate record.** Optional top-level key `gate` of `screamingface.combine-evidence.v1`, written only when the spec has a gate, so every existing evidence keeps its bytes. Key order of the record: `observe`, `observed`, `cmp`, `threshold`, `passed`, `branch`, `otherwise`. Place: after `declared`, before `result` (the order rule of parts 2 and 3: `signal`, `cut`, `declared`, `gate`, `result`). | [erd §4](erd.md), C3 |
| P10 | **Missing numbers.** When the gate runs and the observed number is None (the chosen member has no value, or no member has a value for a mean), the comparison is false: `passed: false`, `branch: "fallback"`. When the vote itself finds no answer (no voters, or the reduce step abstains), the gate does not run: `observed: null`, `passed: null`, `branch: null`, and the result keeps the vote's own reason (`no_votes`). The fallback reply is not read then. | [gate-decision](prd/gate-decision.md) GD-D1–D3 |
| P11 | **`agreement` is the recorded number.** The gate reads the evidence `agreement` as the select step computes it (E/combine/operators/select.py:42-48): the winner's count over the voters for a plain vote, the winner's weight share for a weighted vote. The record's `observed` equals the evidence `agreement` exactly, so a reader can replay the comparison from the evidence alone. | [gate-decision](prd/gate-decision.md) GD-D6 |
| P12 | **`chosen:<name>` and `mean:<name>`.** `chosen:<name>` is the value of the vote's chosen member (`selection.chosen[0]`) for that declared name. `mean:<name>` is `math.fsum` of the non-None values of that name over every member row (any status), divided by their count. | [gate-decision](prd/gate-decision.md) GD-5, GD-6 |
| P13 | **New abstain reason `gate_not_met`.** It is appended to `AbstainReason` and `AnswerReason` on both sides (the E4a precedent of `output_missing`, and the binding test ST/test_evidence_words.py:372 needs the two sides equal). It is a scored decline. It is not an error and not a failure code. E4c's `fail_closed` will be a failure code, so the two never share a status code. | [gate-record](prd/gate-record.md) GR-5 |
| P14 | **Evidence on the fallback branch.** `tally`, `agreement` and `tie` stay the vote's numbers. `chosen` is `[<judge pick>]` for a judge, `[]` for a writer and for an abstain. `built` is true only for a writer. The judge reading goes into the existing `judge` key (`returns: "label"`). `presentation_order` is `"author"` when the fallback judge reading is recorded, and keeps today's rule otherwise. | [gate-decision](prd/gate-decision.md) GD-2–GD-4 |
| P15 | **Verifier slot (ans:Q4).** `sf.Vote(verify=None)`: the attribute `verify` is always None; any other value raises `ValueError` that names `verify=` as reserved. The combine spec gets NO key in this part: a later part adds an optional `verify` key, as this part adds `gate`. The evidence model has an optional field `verifier` typed `null`, never written; the schema snapshot shows it. The SDK decoder accepts the key only with the value `null`. | [verifier-slot](prd/verifier-slot.md) |
| P16 | **Display (part 4 surfaces).** The Case pane gets one gate chip after the agreement chip. The run summary gets one gate line per gated step. The JSON export carries the record in `operations[].combine.gate` with no export change. The report-trace.v1 field set does NOT change: a `branch` trace kind is E4c's report-trace.v2 (docs/spec/2026-10-02-e4a-gap-closure/00-overview.md:131). The judge-link rule gets J4 (a fallback judge that was read), so the judge chip and `judge_model` name the fallback judge. | [gate-display](prd/gate-display.md) |
| P17 | **Rebuild.** `Url4.to_python()` rebuilds a gated vote: the gate, its fallback judge or model, `verify` left out. A spec with `gate` rebuilds only as `sf.Vote`, never as `sf.Reduce`. A hand-edited url4 (a gate on another reducer, a fallback call with no gate, a gate whose fallback call is missing) fails with the existing "cannot rebuild" error. | [gate-api](prd/gate-api.md) GA-5, GA-D4 |
| P18 | **Context signal keys.** The Engine context accepts `fallback_judge` and `fallback_writer` (the `_SIGNAL` pattern, E/combine/spec.py:53). A fallback signal that the spec gate does not name is refused with `combine_spec_invalid`. A fallback signal that the fallback branch needs and that is absent is refused with `combine_spec_invalid`. | [gate-decision](prd/gate-decision.md) GD-E2, GD-E3 |
| P19 | **Contract data.** The evidence contract fixture gets five gate scenarios (`vote_gate_majority`, `vote_gate_abstain`, `vote_gate_judge`, `vote_gate_writer`, `vote_gate_not_run`): 32 → 37 cases. Each gated recipe gets an SDK-compiled url4 fixture with its own drift guard, and the Engine runs it offline. | [gate-decision](prd/gate-decision.md) GD#19, [gate-api](prd/gate-api.md) GA#17 |
| P20 | **No log change.** The one combine log line keeps its format; a gate abstain logs `outcome=abstain_gate_not_met` through the existing rule (E/combine/endpoint.py:244-245). | GD-D8 |
| P21 | **The core stays pure.** The gate logic is a new pure module `E/combine/gate.py` (no I/O, no clock), called by `endpoint._decide`. The layering gate enforces it. | C9 |

## 7. Open and deferred

| # | Item | Default |
|---|---|---|
| D1 | The skip: the fallback call does not run when the gate passes | E4c (OME-1291) |
| D2 | A `returns="scores"` judge as the fallback | not planned; an additive `otherwise` value later |
| D3 | A gate on `sf.Median`, `sf.Mean`, `sf.Pick` or the `sf.Reduce` block forms | not planned |
| D4 | Several signals in one gate, sums with coefficients, an abstain band | part 6 |
| D5 | The verifier check itself, and "try the runner-up, else abstain" | a later part (ans:Q4) |
| D6 | A `branch` trace kind and the "stages that did not run" in the trace | E4c, report-trace.v2 |

Scope notes:

- **N1** The fallback call runs and costs money on every Case, also when the gate passes (ans:Q1).
  The cost shows in the Case accounting as a `judge` or `writer` operation. The README says so.
- **N2** `agreement` counts the voters (the members that gave a usable vote), not the panel size.
  Three members, one failed, two agree: agreement is 1.0. This is the E4a rule.
- **N3** A writer that replies with empty text gives an empty answer, as a model synthesizer does
  today. It is not an abstain.
- **N4** A judge-weighted vote (`judge=sf.Judge(..., returns="scores")`) with a judge fallback has
  two `judge` operations. The judge chip then shows no model, by the existing rule "exactly one
  judge operation" (S/_case_views.py:210-212).
- **N5** Under a quorum panel, the fallback judge gets the panel form of its template, and the
  writer reads the panel (the existing `_compile_signals` rule, S/_evaluation/reducer_signals.py:130,152).

## 8. Owner-approved test edits (needed at build)

The build lists each file below as a pinned edit. The owner approves them after the build (plan §6).
No approval manifest is written by the build.

| File | Unit | Why |
|---|---|---|
| `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json` | 1 | new optional `gate` (frozen by `ET/test_wire_schema_freeze.py`) |
| `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` | 1 | new optional `gate`, `verifier`; `gate_not_met` in two reason enums |
| `ST/data/schemas/screamingface.answer.v1.json` | 1 | `gate_not_met` in `abstain_reason` and `reason` |
| `ST/public_surface_snapshot.json` | 1, 3 | `sf.report.CombineGate`, `CombineEvidence.gate` (unit 1); `sf.Gate`, `Vote.__init__` `gate`, `verify` (unit 3) |
| `ST/test_pick_output.py:250-264` | 1 | the exact sorted reason lists of `answer.v1.json` gain `gate_not_met` |
| `ST/test_evidence_words.py:372` and `:460-475` | 1 | `len(ANSWER_REASONS)` 12 → 13; the exact `answer.v1.json` dict |
| `ET/test_combine_pick_output.py:341-352` | 1 | the exact `AbstainReason` tuple, the last `AnswerReason`, the last word of each `no_votes` enum list |
| `ET/test_combine_evidence_words.py:310-322` | 1 | the exact `AnswerRecord.reason` enum list gains `gate_not_met` |
| `ET/data/combine_contract/evidence_cases.json` | 2 | five new gate cases; the 32 existing cases keep their bytes |
| `ET/test_combine_evidence_contract_fixture.py` | 2 | five new scenario builders and `SCENARIOS[...]` lines (append only) |
| `ST/test_combine_evidence_contract.py:54` | 2 | one appended `_EXPECTED_NAMES \|= {...}` line |
| `ST/test_frozen_record_fields.py:184` | 2 | the case count 32 → 37 |

Units 4 and 5: no pinned file. If the append-only gate names another file, the unit stops and the
ledger records it as a deviation.

## 9. What changes for related work

- **E4c (OME-1291).** E4c reads the spec `gate` object, finds the fallback call by its topology
  signal key (`fallback_judge` or `fallback_writer`), evaluates the vote and the gate from the
  members only, and calls the fallback only on the fallback branch. FB-I1 makes the evidence the
  same bytes. E4c adds `fail_closed` as a failure code and the `branch` trace kind in
  report-trace.v2. The combine spec, the context keys and the evidence record do not change.
- **E4b part 6** (several signals in one step, the abstain band) can extend `observe` with new
  forms; the record keeps its keys.
- **The verifier part** adds the optional spec key `verify` and writes the reserved `verifier`
  record.

## 10. Build errata

None yet. The build appends here.

# PRD: Lazy gate fallback — the E4b fallback call runs only on the fallback branch

**Source:** epic OME-1291 behavior 2 and E4b DB-5 ("E4b records the gate … E4c makes the fallback
call not run"), ans:Q1, ans:Q6, ans:Q7 · **Priority:** P0 (the first real user of the branch core)
**Lifecycle:** existing (characterize + delta) · **Owner:** unassigned
Paths: [erd §3, §6, §7](../erd.md) · contracts: C2, C3, C6 · component: [branch-core](branch-core.md)
· related: [gate](gate.md) (general panel gates), [budget](budget.md) (a refused fallback),
[report](report.md) (which evidence the Combine section shows)

## 1. Summary and user story

As a researcher with a gated majority vote (`sf.Fanout(ms) >> sf.Gate(when=sf.agreement() >= 0.7,
then=sf.Vote(), otherwise=sf.JudgePick(j))`), I want the judge (or the writer) to run only on the
Cases where the gate fails, so that the saving my method claims is real money and the run cost shows
it, while the evidence that I read and replay stays exactly what E4b writes today.

## 2. Background and constraints

- "If it is at least a threshold, the answer is the majority member's text and the fallback does
  not run. … That skipped call is the point. Implementing the skip is E4c's mechanism."
  [existing `docs/spec/2026-10-16-e4b-gate-record/00-overview.md:110-116`]
- "E4b records the gate … E4c (OME-1291) makes the fallback call not run." [existing
  `docs/spec/2026-10-16-e4b-gate-record/00-overview.md:211-216`]
- "E4c reads the spec `gate` object, finds the fallback call by its topology signal key
  (`fallback_judge` or `fallback_writer`), evaluates the vote and the gate from the members only,
  and calls the fallback only on the fallback branch. FB-I1 makes the evidence the same bytes."
  [existing docs/spec/2026-10-16-e4b-gate-record/00-overview.md:211-215]
- "E4c can skip the call on the majority branch and on the "not run" branch and produce the same
  evidence bytes" (C8); the same holds for the band branch (part 6 C8). [existing
  docs/spec/2026-10-16-e4b-gate-record/contracts.md:124-136; docs/spec/2026-10-16-e4b-signal-sums/
  contracts.md:96-104]
- Mechanism: the gated iterate; no url4 grammar change. [stated ans:Q1]
- `sf.Gate` is the general branch construct. [stated ans:Q6] This PRD keeps the E4b fallback forms
  (`otherwise=sf.JudgePick(...)` / `sf.Synthesize(model)`); a recipe `otherwise` is [gate](gate.md).
- Adaptive sampling is a Cascade over sample panels; the consistency samples themselves are not made
  lazy. [stated ans:Q7] This resolves the E4b part 7 note "Skipping the extra calls is not in E4c's
  scope today (D8)" (docs/spec/2026-10-16-e4b-consistency/00-overview.md:215-216): D8 stays true for
  `sf.Consistency` samples; E4c covers adaptive sampling only through [cascade](cascade.md).

### 2.1 Current behavior

- The SDK compiles a judge or writer fallback as one model call per gated vote: `GateNode._signal_call`
  returns the label judge's call under key `fallback_judge`, or a writer call under `fallback_writer`
  (`S/gate.py:91-107`; keys `S/reducer.py:73-77`) [existing]. `_model_signal_source` appends it as a
  `judge_N` / `writer_N` source with the `binding` param and an operation `op_judge_N` /
  `op_writer_N` (`S/_evaluation/reducer_signals.py:215-253`) [existing].
- The combine call reads that reply through its context `signals` and depends on the call
  (`S/_evaluation/candidate.py:686-715`; `_append_combine` `:910-936`) [existing]. The url4 executor
  gathers every dependency first (`U/dag/executor.py:168-184`), so the fallback call runs on every
  Case [existing]. The SDK says so: "In this version the fallback call runs on every Case"
  (`S/gate.py:7`, `:48`; `S/_surface/gate.py:44`; `packages/screamingface/README.md:1098`, `:1206`)
  [existing].
- The Engine: `_combine` checks the context keys (`check_fallback_signals`, `E/combine/endpoint.py:413`;
  CX-I1 `E/combine/gate.py:106-110`), then `_decide` (`:789-833`) runs reduce, select and `_gated`
  (`:865-919`). `_gated` checks the band, compares, writes the gate record and takes one branch;
  only `_fallback` (`:922-975`) reads the reply, through `fallback_label` / `fallback_text`
  (`E/combine/gate.py:89-103`) — FB-I1 [existing]. When the vote has no voter, `_not_run`
  (`:978-982`) writes a gate record with no branch and no reply is read (GR-I1) [existing].
- A context with no fallback key is valid on the majority branch
  (`ET/test_combine_gate.py:371` `test_majority_branch_never_reads_the_fallback_reply`) and on the
  band branch (`ET/test_combine_band.py:482`) [existing]. On the fallback branch it is
  `combine_spec_invalid` "the gate fallback needs the fallback_<x> signal"
  (`E/combine/gate.py:98-103`; `ET/test_combine_gate.py:438`) [existing].
- A combine call takes exactly one param, `binding=synthesis_N` (`E/combine/endpoint.py:1040-1044`)
  [existing]. The world endpoint records every outcome with `record_combine_call`
  (`E/world/combine.py:67-79`) [existing]. `CombineOutcome` always has evidence
  (`E/combine/endpoint.py:357-361`) [existing].
- The Case is abstained when its root intent is exactly `$name` of an abstained combine operation
  (`E/benchmarks/operation_outputs.py:94-111`) [existing].
- A fallback failure fails the Case on every branch, because the call always runs (E4b part 5 owner
  decision, CHANGELOG) [existing].

### 2.2 Delta

1. **SDK compile (judge or writer fallback only).** One gated vote compiles to: the decision call
   (call #1: today's combine call, with no fallback key in its context and the extra param
   `phase=decide`) → DECIDE → OPEN(`otherwise`) → a gated iterate whose body is the fallback call
   and call #2 (the same spec, today's context with the fallback key) → JOIN. The `then` slot of
   JOIN is call #1 itself (the step body is the decision call's own reducer, [branch-core](branch-core.md) D4). A gate
   with `otherwise=sf.abstain()` (or the E4b word `"abstain"`) keeps today's one-call compile,
   byte for byte. [proposed — ans:Q1]
2. **Engine combine.** `_binding` accepts `{binding}` or `{binding, phase}` with `phase == "decide"`.
   With `phase=decide`, the fallback branch returns a **pending outcome**: output `""` and no combine
   evidence. The outcome is published with `pending=True` and carries the gate record (branch
   `fallback`) on `OperationCall.gate_record`, where DECIDE reads it through
   `current_operation_calls()` by call #1's fingerprint ([branch-core](branch-core.md) D11);
   nothing is kept in request scope. Attribution gives call #1 no evidence, and the accounting
   index and the budget fold skip it ([branch-core](branch-core.md) D3, BC-29). With
   `phase=decide`, a context that holds a fallback key is `combine_spec_invalid`. Without the
   param, nothing changes (a missing key on the fallback branch stays `combine_spec_invalid`).
   [proposed]
3. **DECIDE (panel kind)** runs after call #1 (its AFTER source references `$synthesis_N`,
   [branch-core](branch-core.md) D10), reads call #1's pending or complete gate record (D11) and maps
   it by the panel branch rule of [branch-core](branch-core.md) D4: `majority` → `then`; `fallback`
   → `otherwise`; `band` → no branch, abstain `in_band`; null → no branch, call #1's own abstain
   (`no_votes`, `cut_not_met`) stands, because a JudgePick or Synthesize `otherwise` is a step;
   subject to [budget](budget.md). [proposed]
4. **JOIN** reads `decision.branch` and returns call #1's output text on `then` and call #2's
   output text on `otherwise` (plain text, [branch-core](branch-core.md) D2); on `then` and on no
   branch it copies call #1's combine result (answered, or abstain with its reason) into the
   decision record's `result`, and on `otherwise` it copies call #2's: call #2 is the `otherwise`
   terminal in GATE_SPEC `terminal` ([branch-core](branch-core.md) D12), and JOIN finds its recorded
   result by fingerprint. So an E4b vote that abstains still marks the Case abstained (BC-32), on
   either branch. [proposed — branch-core BC-4, BC-8; review 3 F6]
5. **Docs and words.** Every "the fallback call runs on every Case" statement changes to "the
   fallback call runs only when the gate fails". The CHANGELOG states the behavior change: a
   fallback failure now fails the Case only on the Cases where the fallback runs. [implied]

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **LF-1 Majority = no fallback call.** Given a gated vote with a judge fallback and a Case whose
  agreement passes the gate, When the Case runs, Then no `judge_N` call is sent, the answer is the
  majority answer, and the decision record lists `{"branch": "otherwise", "reason":
  "not_selected", "model_calls": {"min": 1, "max": 1}}`. [stated epic; stated ans:Q1; stated
  ans:Q22]
- **LF-2 Fallback branch runs it once.** Given the same gate and a Case whose agreement fails, When
  the Case runs, Then exactly one `judge_N` call is sent, call #2 runs once, and the answer is the
  member the judge names, byte for byte. [implied — E4b decision DB-5, OME-1290]
- **LF-3 Writer fallback.** Given `otherwise=sf.Synthesize(model)`, Then LF-1 and LF-2 hold for the
  `writer_N` call; on the fallback branch the writer's text is the answer (8 MiB cap first, as
  today). [existing `E/combine/endpoint.py:922-975`]
- **LF-4 Same evidence bytes.** Given the E4b gate scenarios of
  `ET/data/combine_contract/evidence_cases.json` (majority, fallback judge, fallback writer, band,
  not run), When each runs through the new compile, Then the final combine evidence (call #1 on
  majority/band/not run, call #2 on fallback) is byte-identical to today's evidence for that
  scenario. [existing `docs/spec/2026-10-16-e4b-gate-record/contracts.md:124-136`]
- **LF-5 Band = no fallback call.** Given a gate with `abstain_if=` and a number inside the band,
  Then no fallback call is sent and the Case abstains with `in_band`. [existing `docs/spec/2026-10-16-e4b-signal-sums/contracts.md:91-104`]
- **LF-6 No voter = no fallback call.** Given every member fails or abstains (quorum panel), Then
  the gate does not run (GR-I1), no fallback call is sent and the Case abstains with `no_votes`.
  [existing `E/combine/endpoint.py:978-982`]

### 3.2 Error paths

- **LF-7 Fallback failure, fallback branch.** Given the fallback call fails permanently on a Case
  whose gate fails, Then the Case fails with the fallback call's own code (as today).
  [existing `docs/spec/2026-10-16-e4b-gate-record/contracts.md:27-40`]
- **LF-8 Fallback failure cannot happen on the majority branch.** Given a provider that would refuse
  the fallback call, When the gate passes, Then the Case is scored with the majority answer,
  because the call is never sent. This is the stated behavior change. [implied]
- **LF-9 Decision call with a fallback key.** Given a hand-edited url4 whose `phase=decide` call
  holds a `fallback_judge` key, Then the call fails with `combine_spec_invalid` ("a decision call
  reads no fallback signal"), the message names no value. [proposed]
- **LF-10 Unknown phase.** Given `phase=final` or any other value or key, Then `_binding` refuses it
  with `combine_spec_invalid` ("a combine call takes binding=synthesis_N and optionally
  phase=decide"). [proposed]
- **LF-11 Judge names no present member.** Given the fallback judge reply names no kept member, Then
  call #2 fails as today (`judge_reply_invalid` path, `ET/test_combine_gate.py:419`), and only on the
  fallback branch. [existing]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| LF-12 | Replay takes the same branch | [implied — GD-I6] | H×M | Given a captured run with fallback and majority Cases, When it replays from the pinned cache, Then the same Cases send the fallback call and no replay asks for a call the capture does not hold. |
| LF-13 | Pending outcome never reaches the Case | [proposed — gap §per-flow/failure] | H×M | Given call #1 returns the pending outcome, Then its `""` output is never the Case answer: JOIN takes call #2, and `op_<call #1>` carries no `combine` key on that Case. |
| LF-14 | Abstained final node | [implied — branch-core BC-8] | H×M | Given call #1 abstains (`in_band`, `no_votes`, `cut_not_met`) or call #2 abstains, Then the Case is scored 0 with `abstained: true` through JOIN's `decision.result` (call #2 is the `otherwise` terminal, branch-core D12). |
| LF-15 | Run cost drops | [stated epic] | H×M | Given 10 Cases of which 3 fail the gate, Then the run has 3 `op_judge_N` accounting rows (not 10), the synthesis-stage cost counts only those 3, and the decision records list 7 not-run fallback bodies. |
| LF-16 | Judge-weighted vote with a judge fallback | [existing `ET/test_combine_gate.py:623`] | M×M | Given `sf.Judge(j) >> sf.Gate(..., then=sf.Vote(weights="score:judge"), otherwise=sf.JudgePick(j2))`, Then the scores judge stays a dependency of call #1 (it runs every Case) and only the label judge moves into the gated body. |
| LF-17 | Quorum panel gives the fallback the panel | [existing `ST/test_gate_api.py:713`] | M×M | Given a quorum panel with a failed optional member, Then the fallback call in the body reads the same panel context as today. |
| LF-18 | Fallback params still preflighted | [existing `ST/test_gate_api.py:729`] | M×L | Given fallback params, Then they stay in `parameter_assignments` and the preflight checks them before any spend, even though the call may not run. |
| LF-19 | `to_python` round trip | [existing `ST/test_gate_api.py:757`] | M×M | Given the new url4, Then `Url4(...).to_python()` rebuilds `sf.Gate(..., otherwise=sf.JudgePick(...))` and the rebuild recompiles to the same bytes (RB-1). |
| LF-20 | Old one-call url4 still runs on the Engine | [implied — delta 2] | M×L | Given an E4b-era url4 (no `phase` param, fallback call in the combine deps), Then the Engine runs it as today (the fallback runs every Case). The SDK never emits it again. |
| LF-21 | Operation ids and member order | [proposed] | M×M | Given the new compile, Then call #1 keeps the binding `synthesis_N`, the fallback keeps `judge_N`/`writer_N`, call #2 takes the next `synthesis_M`, and every combine operation lists its member producers first in `depends_on` (`S/_case_views.py` reads `depends_on[:len(members)]`). |
| LF-22 | Consistency samples are not lazy | [stated ans:Q7] | L×M | Given a gated vote over a Fanout with `sf.Consistency(n=5)`, Then the samples run on every Case (they feed call #1), and only the fallback call is gated. |

## 4. Non-functional requirements

- Per gated vote: the cost of 1 more combine call (call #2) and 4 pure endpoint calls on the fallback
  branch; on the majority branch DECIDE, OPEN, JOIN only. Combine is pure CPU; target < 10 ms extra
  CPU per Case at p99 on the Engine-world host [proposed].
- Observability: the combine log line (FW-17) gets the value `fallback_pending` for the pending
  outcome; JOIN logs the branch (branch-core §4) [proposed].
- Security: the pending outcome holds no reply text; the request-scope gate record holds only the
  numbers and words of `GateRecord` [proposed].

## 5. Out of scope

- A recipe `otherwise` (a whole model or panel on the original question) and a panel gate whose
  `then` is not a Vote: [gate](gate.md). [stated ans:Q6]
- Making `sf.Consistency` samples lazy; adaptive sampling is [cascade](cascade.md). [stated ans:Q7]
- What a budget refusal of the fallback gives: [budget](budget.md). [stated ans:Q3, ans:Q19]
- A `returns="scores"` judge as a fallback (E4b D2, not planned). [existing
  `docs/spec/2026-10-16-e4b-gate-record/00-overview.md`]
- The Combine section layout for a gated step: [report](report.md).

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: Engine core-out (CHAR rows first, then the combine param and the pending outcome, then the SDK
compile, then Engine-world runs and the byte-identity checks). PIN rows are owner-approved edits of
pinned files (`.claude/test-change-approvals/`); agents never write the manifest.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `majority_branch_never_reads_the_fallback_reply` (`ET/test_combine_gate.py:371`) | unit | [existing] | H×M | passes today |
| 2 | CHAR `band_wins_and_reads_no_fallback_reply` (`ET/test_combine_band.py:482`) | unit | [existing] | H×M | passes today |
| 3 | CHAR `fallback_branch_without_its_signal_is_spec_invalid` without `phase` (`ET/test_combine_gate.py:438`) | unit | [existing] | H×M | passes today; stays green (LF-20) |
| 4 | `decision_call_fallback_branch_returns_the_pending_outcome` (output `""`, no evidence, gate record branch `fallback`) | unit | LF-2 delta 2 | H×H | `_gated` pending path; `CombineOutcome.pending` |
| 5 | `decision_call_majority_and_band_evidence_equal_todays_bytes` (fixture V cases) | unit | LF-4 | H×H | no change on those branches |
| 6 | `judge_fallback_vote_sends_no_judge_call_when_the_gate_passes` (Engine world, fake gateway counts `judge_1` calls) | integration | LF-1 | H×H | SDK compile delta 1 |
| 7 | `judge_fallback_vote_sends_one_judge_call_when_the_gate_fails` | integration | LF-2 | H×H | gated body: fallback + call #2 |
| 8 | `writer_fallback_runs_only_on_the_fallback_branch` | integration | LF-3 | H×H | same, writer |
| 9 | `final_evidence_is_byte_identical_for_the_five_gate_scenarios` | integration | LF-4 | H×H | call #2 = today's context |
| 10 | `pending_output_never_becomes_the_case_answer` | integration | LF-13 | H×M | JOIN takes call #2; no `combine` on `op_<call #1>` |
| 11 | `abstained_decision_or_final_call_marks_the_case_abstained` (parametrized: in_band, no_votes, call #2 abstain) | integration | LF-14 | H×M | JOIN copies call #1 or the `otherwise` terminal (call #2); `final_operation_abstained` |
| 12 | `fallback_failure_fails_the_case_only_on_the_fallback_branch` | integration | LF-7, LF-8 | H×M | — |
| 13 | `replay_sends_the_fallback_on_the_same_cases` | integration | LF-12 | H×M | DECIDE reads only call #1's record |
| 14 | `decision_call_with_a_fallback_key_is_spec_invalid` | unit | LF-9 | M×M | `phase=decide` check |
| 15 | `combine_call_refuses_an_unknown_phase_or_param` | unit | LF-10 | M×M | `_binding` |
| 16 | `run_accounting_counts_only_the_fallback_calls_that_ran` | integration | LF-15 | H×M | — |
| 17 | `scores_judge_stays_in_call_one_and_label_judge_moves_to_the_body` | unit | LF-16 | M×M | `_vote_plan` split |
| 18 | `operation_ids_keep_synthesis_judge_writer_patterns_and_member_order` | unit | LF-21 | M×M | next `synthesis_M` for call #2 |
| 19 | `gated_vote_url4_round_trips_through_to_python` (new shape) | unit | LF-19 | M×M | `S/url4.py` rebuild of the gated form |
| 20 | `e4b_one_call_url4_still_runs_on_the_engine` | integration | LF-20 | M×L | Engine unchanged without `phase` |
| 21 | `consistency_samples_run_on_every_case_under_a_lazy_gate` | integration | LF-22 | L×M | — |
| 22 | `gate_docs_say_the_fallback_runs_only_when_the_gate_fails` (README, `S/gate.py`, `S/_surface/gate.py` docstrings, CHANGELOG behavior line) | unit | delta 5 | M×M | text edits |
| 23 | PIN `ET/data/combine_contract/gate_judge_vote_candidate.url4` and `gate_writer_vote_candidate.url4` (new compile shape; `gate_abstain`, `gate_band`, `gate_verbalized` stay byte-equal) | unit | delta 1 | H×M | owner approval; read by `ET/test_combine_gate_run.py`, `ST/test_gate_contract_fixtures.py` |
| 24 | PIN `ST/test_gate_api.py` rows that assert the one-call shape (`:592` `test_judge_fallback_compiles_one_label_judge_call`, `:653` writer, `:757` round trip, `:839` two fallback calls, `:869` two judge calls) | unit | delta 1 | H×M | owner approval; rewrite to the gated shape |

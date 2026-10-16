---
ticket: unfiled   # epic OME-1290 is the parent; the leaf is filed at PR-open
stack: screamingface-engine, screamingface, repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-16
finished:
---

# e4b-gate-record — E4b part 5, gate record and verifier slot

One ledger for the whole part. The plan is
[docs/plan/2026-10-16-e4b-gate-record.md](../plan/2026-10-16-e4b-gate-record.md). The spec is
[docs/spec/2026-10-16-e4b-gate-record/](../spec/2026-10-16-e4b-gate-record/00-overview.md).
Branch `e4b-gate-record`, base `4e622af75` (part 4, on parts 3 and 2). Each unit gets its own
section below, in the order of plan §2.

## Spec

### Intent

Give `sf.Vote` a gate: a comparison of one named number (the agreement, a declared signal of the
chosen member, or the mean of a declared signal over the members) against one threshold, written as
data. When the comparison holds, the answer is the majority. When it does not, the fallback gives the
answer: an abstain with the new reason `gate_not_met`, a label judge that names a member, or a model
that writes. The fallback call still runs on every Case; the combine step chooses and records the
comparison and the branch in a new optional evidence record `gate` (ans:Q1). The vote gets a reserved
`verify=None`, and the evidence reserves an optional `verifier` key (ans:Q4). The part 4 surfaces
show the gate. E4c can add the skip with no wire change, because the majority branch never reads the
fallback reply.

### Owner decisions (verbatim)

- Q1 gate effect: "Chooses + records (Recommended)".
- Q2 gate input (multi): "Agreement (Recommended)", "Chosen member's signal", "Mean over members".
- Q3 fallbacks (multi): "Abstain (Recommended)", "Judge that copies", "Writing model".
- Q4 verifier slot: "Reserved param + key (Recommended)".

### Spec files (commit `docs(e4b): spec and plan for E4b part 5 (gate record and verifier slot)`)

- `docs/spec/2026-10-16-e4b-gate-record/00-overview.md` (P1–P21, N1–N5, D1–D6)
- `docs/spec/2026-10-16-e4b-gate-record/erd.md`, `contracts.md`, `test-plan.md`
- `docs/spec/2026-10-16-e4b-gate-record/prd/`: `gate-record.md` (GR, 14 rows), `verifier-slot.md`
  (VS, 6), `gate-decision.md` (GD, 20), `gate-api.md` (GA, 20), `gate-display.md` (GS, 12),
  `docs.md` (DC, 5). 77 rows; 81 rows after the spec review (GR 17, GD 21).
- `docs/plan/2026-10-16-e4b-gate-record.md`

### Units

Units after the spec review (plan §2 is the source):

| # | Slug | PRD rows | Stacks | Pinned files |
|---|---|---|---|---|
| 1 | gate-record | GR#1, GR#3–11, GR#13, GR#17, VS#1–3 | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`, `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`, `ST/public_surface_snapshot.json` |
| 2 | gate-decision | GD#1–21, GR#2, GR#12, GR#14–16 | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`, `ST/data/schemas/screamingface.answer.v1.json`, `ST/test_pick_output.py` (:250-264), `ST/test_evidence_words.py` (:372, :460-475), `ET/test_combine_pick_output.py` (:341-352), `ET/test_combine_evidence_words.py` (:310-322), `ET/data/combine_contract/evidence_cases.json`, `ST/test_frozen_record_fields.py` (:184); append-only, not flagged: `ET/test_combine_evidence_contract_fixture.py`, `ST/test_combine_evidence_contract.py` |
| 3 | gate-api-core | GA#1, GA#2, GA#5–9, GA#12a, GA#17a, GA#18a, GA#19, GA#20, VS#4–6 | screamingface-engine, screamingface, repo | `ST/public_surface_snapshot.json` |
| 4 | gate-api-fallback | GA#3, GA#4, GA#10, GA#11, GA#12b, GA#13–16, GA#17b, GA#18b | screamingface-engine, screamingface, repo | none |
| 5 | gate-display | GS#1–12 | screamingface, repo | none |
| 6 | docs | DC#1–5 | screamingface, repo | none |

`ET/` = `apps/screamingface-engine/tests/unit/`, `ST/` = `packages/screamingface/tests/`.

### Facts checked on `4e622af75` (intake, line numbers moved after the restack)

- No `.codegraph/` in this worktree; the facts were checked with grep and read.
- Abstain words: `AbstainReason` E/combine/ports.py:53, `AnswerReason` :54-66, `ABSTAIN_REASONS`
  :67, `NoVotes` :115-123. SDK `AbstainReason`, `AnswerReason` S/answer.py:29-45.
- Endpoint: `run_combine` E/combine/endpoint.py:222-246 (the log line :244-245), `_combine`
  :249-275 (`no_votes` with no voter :273-274), `_decide` :411-437, `_abstain` :440-461,
  `_output` :681-692, `_result` :695-706, `_evidence` :736-790 (`presentation_order` keyed on the
  context signal `judge`, :780).
- Evidence: schema id E/combine/evidence.py:35, `ResultRecord` :76-90, `SignalRecord` :93-97,
  `CutRecord` :100-105, `CombineEvidence` :133-192 (`declared` :161-163, then `result`). SDK mirror:
  `_OPTIONAL_EVIDENCE_KEYS` S/_evaluation/combine_evidence.py:64; `CombineEvidence`
  S/combine_evidence.py:258-395.
- `agreement` = winner score / total score in `_tie_and_agreement`
  E/combine/operators/select.py:42-48 (a count share for `mode@1`, a weight share for
  `weighted_mode@1`). No rule reads it.
- Correction to the brief: there is no `E/combine/operators/fusion.py`. The quorum is the SDK
  `_quorum` (S/fusion.py:245-252) and the url4 panel; it is a member floor, not a gate.
- `filter@1` threshold: `_check_threshold` E/combine/operators/signals.py:107, `_passes_threshold`
  :134, `filter_members` :148. `top_k@1` `cut_not_met`: E/combine/operators/selection.py:93-111.
- Context signals: `_SIGNAL = judge|writer_...` E/combine/spec.py:53; `judge_reply`
  E/combine/ports.py:601-613; `parse_label` is in the plugin E/combine/operators/judge.py:47-52 and
  is imported by `ET/test_combine_judge.py:21` from there.
- SDK: `Vote` S/reducer.py:458-557; `_ReducerPlan` :65-85; `_ModelSignal` :52-62; `Judge`
  S/judge.py:141-232; `judge_intent` :129-138; `judge_from_signals` :275-295; `_check_reads`
  S/fusion.py:165-181; `combine_spec_text` S/_evaluation/combine_spec.py:45-82,
  `_OPTIONAL_SPEC_KEYS` :23; `_compile_signals` S/_evaluation/reducer_signals.py:98-167,
  `_signal_call_role` :170-184; `_operation_shape` S/_evaluation/topology.py:91-105, `_signal_role`
  :503-508, `_decode_signal` :511-525; `_rebuilt_reducer` S/url4.py:538-555, `_model_signal`
  :558-575; the model synthesizer prompt default S/_evaluation/candidate.py:502 and its rebuild
  rule S/url4.py:284.
- The corrective loop has an internal `GATE_ROUTE` (S/_evaluation/corrective.py:57,
  E/benchmarks/ensemble/policy.py:23). No public `Gate` exists.
- Part 4 surfaces: `_chips` S/_ui/combine_view.py:176-193; `_StepSummary` :296-321;
  `_summary_html` :323-338; `_reads_judge` S/_case_views.py:181-192; `_judge_link` :195-215; the
  export writes `operations[].combine` (S/case_result.py:333-336). The report-trace.v1 reduce field
  set is pinned by ST/test_judge_link_trace.py:430-451 and ST/test_e4b_schema_pins.py:24-25.
- Abstain path to coverage: `final_operation_abstained` E/benchmarks/operation_outputs.py:94-111
  reads `combine.result.status`.
- Tests that enumerate the words (pinned in unit 2 after the spec review; first planned for unit 1): ST/test_pick_output.py:244-264,
  ST/test_evidence_words.py:361-372 and :456-475, ET/test_combine_pick_output.py:340-352,
  ET/test_combine_evidence_words.py:303-322. ET/test_combine_evidence_contract_fixture.py:418-421
  needs every `AbstainReason` in the scenarios, so unit 2 adds the gate scenarios.
- Signal-key bind: ST/unit/test_signal_key_conformance.py:115-158 reads the Engine `_SIGNAL`
  literal with `ast`; one string literal keeps it working.
- Docs constraints: ST/test_show_signals_docs.py:24-35 (counted tokens), :67-72 (headings between
  Browse and Accounting), :102-110 (part 4 and part 3 bullets at positions 0 and 1).

### Spec review (2026-10-16)

A design review of the spec gave 6 MAJOR and 12 MINOR findings. All are applied in the commit
`docs(e4b): review fixes for the E4b part 5 spec`. No finding contradicts an owner answer.

| # | Sev. | Finding | Applied as |
|---|---|---|---|
| 1 | MAJOR | `gate_not_met` in unit 1 turns `ET/test_combine_evidence_contract_fixture.py:413-421` red (the scenario that uses the word is in unit 2) | The word, GR-I3 and their pinned edits moved to unit 2 (gate-record build split; GR#2, 12, 14, 15, 16). GR-2 and GR-3 now use a majority-branch record, because unit 1 has no word. GR#13 split into GR#13 (unit 1) and GR#15 (unit 2); GR-D6 got its own row GR#17 (unit 1). |
| 2 | MAJOR | GR#1 and GA#1 use open sets (a glob, the whole file) | Fixed lists L32 and L43 in test-plan §6, taken on `4e622af75`. GS#1 (GS-D3) uses L32 too. |
| 3 | MAJOR | A fallback judge can name an excluded member, and CE-I3 raises an undeclared ValidationError | GD-E6 and GD#21: the label is parsed over `kept` (the present members whose `_record_status` is not `excluded`). GR-I5(b) has the same rule on the SDK side. Deviation from the review text: the review oracle `{agreement, >=, 0.99, judge}` passes the gate, because `vote_weight_excluded` has `agreement = 1.0`. The spec uses `{agreement, >, 1.0, judge}`, which takes the fallback. |
| 4 | MAJOR | The keep polarity of `cmp` cannot hold E4c's `agreement < 0.8` as written | Kept the keep polarity as [proposed]. P4, C1, C8 and plan §6 now ask the owner to decide it, with the escalate polarity as the other choice. |
| 5 | MAJOR | `_answer_fixtures.fixture_case` cannot load the gate cases | gate-display §3 and §7: read `COMBINE_CONTRACT / "evidence_cases.json"` under `@requires_engine_app` and build the Case by hand (`ST/test_member_exclusion.py:_case`). No edit of `ST/data/combine_evidence_cases.json`. |
| 6 | MAJOR | Unit 3 is too large | Split into unit 3 (gate-api-core) and unit 4 (gate-api-fallback); rows 12, 17, 18 have `a` / `b` halves. Deviation from the review text: GA#7 (the constructor refuses a scores judge, a named model, a recipe) stays in unit 3, because the full constructor is in unit 3 and GA#19 shows a Model fallback. Unit 3 stubs the Judge and Model branches of `_signal_call` with `NotImplementedError`. |
| 7 | MINOR | GR-I5 has no branch condition | GR-I5 is two rules, each on `branch == "fallback"` (erd §4; GR-E3). |
| 8 | MINOR | How the fallback reading reaches `_evidence` | `_gated` passes `dataclasses.replace(reduction, judge=reading)` (gate-decision delta 4). |
| 9 | MINOR | `_signal_call` rebuilds the judge prompt; the rebuild cannot use `judge_from_signals` | `replace(judge._signal_call(), key="fallback_judge")`; rebuild with `judge_from_signals((replace(signal, key="judge"),), "label")`, no signature change (C7, gate-api). |
| 10 | MINOR | `judge_reply` condition on `key != "judge"` has no effect | The message is always `f"{owner} needs the {key} signal"`. |
| 11 | MINOR | C9 and gate-decision disagree on the imports of `E/combine/gate.py` | Standard library, `combine.ports`, `combine.spec`; never `combine.operators` or `combine.builtins` (C9, P21, gate-decision). |
| 12 | MINOR | "Regenerate with the existing update variable" does not overwrite | Schema snapshots: delete, then `UPDATE_SCHEMA_SNAPSHOT=1`, then a plain run. Deviation from the review text: the public surface snapshot DOES overwrite with `UPDATE_SURFACE_SNAPSHOT=1` (ST/test_public_surface.py:224-236), so it is not deleted first (test-plan §2). |
| 13 | MINOR | The writer `value` is the raw text | P14 option (a): `value = _stages(text, plan)[2]`. GD-4 value `"c written"`; `vote_gate_writer` value `"10"`. |
| 14 | MINOR | GA-2 does not say which form of the prompt has `\n` | The oracle names the decoded `_Call.prompt` (Python form). |
| 15 | MINOR | VS-D1 cites 37 cases in unit 1 | "every case in `evidence_cases.json` (32 at unit 1, 37 after unit 2)"; the row loops over the file. |
| 16 | MINOR | Two docstrings become false | Unit 2 updates the endpoint INVARIANT, `_decide`, and the `operators/judge.py` module docstring. |
| 17 | MINOR | The README names the cost, not the failure risk | New verbatim sentence "If the fallback call fails, the Case fails, also when the gate keeps the majority." in docs §2 and DC#2. |
| 18 | MINOR | Two append-only files are listed as pinned | Marked "append-only, not flagged; no approval needed unless the gate names them" (overview §8, plan §6). |

### Status

Spec written headless from the owner interview of 2026-10-16; spec review fixes applied the same
day. Build not started. The units append
their sections (Intent, Planned changes, Pinned edits, Test plan, Acceptance, Deviations, Outcome)
below.

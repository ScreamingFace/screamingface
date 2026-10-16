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

## Unit 1: gate words, spec key and evidence record (`gate-record`)

### Intent

PRDs `gate-record` (rows GR#1, GR#3–11, GR#13, GR#17) and `verifier-slot` (rows VS#1–3); ans:Q1
("records the comparison and the branch"), ans:Q4 (reserved `verifier`); P1, P3, P4, P9, P15.
The Engine gets the gate words (`GateCmp`, `GateOtherwise`, `GateBranch`, `GATE_OBSERVE`), the
optional spec key `gate` (`GateSpec`, vote only, `_check_gate` with fixed messages), the optional
evidence record `gate` (`GateRecord`, after `declared`, before `result`) and the reserved
`verifier` key (typed null, never written), with GR-I1, GR-I2, GR-I4 and GR-I5. The SDK gets
`sf.report.CombineGate`, `CombineEvidence(gate=...)` with the same checks, a strict `gate`
decoder, a null-only `verifier` rule, and the spec key `gate` in `_OPTIONAL_SPEC_KEYS`. No code
writes a gate record yet (unit 2). The word `gate_not_met` and GR-I3 are unit 2. No schema id
changes; every existing evidence, spec and url4 keeps its bytes.

### Planned changes

- `E/combine/ports.py`: `GateCmp`, `GateOtherwise`, `GateBranch`, `GATE_OBSERVE`, `__all__`.
- `E/combine/spec.py`: `GateSpec`, `CombineSpec.gate`, `_quiet_gate`, `_check_gate`,
  `_check_agreement_gate`, the module INVARIANT, `__all__`.
- `E/combine/evidence.py`: `GateRecord` (`_check`: observe grammar, GR-I1, GR-I2),
  `CombineEvidence.gate`, `CombineEvidence.verifier`, module `_check_gate` (GR-I1 evidence part,
  GR-I4, GR-I5), the module INVARIANT, `__all__`.
- `S/combine_evidence.py`: `GateCmp`, `GateBranch`, `GateOtherwise`, `CombineGate`,
  `_gate_observe`, `_check_gate`, `CombineEvidence.gate`, `__all__`.
- `S/_evaluation/combine_evidence.py`: `_OPTIONAL_EVIDENCE_KEYS` (+ `gate`, `verifier`),
  `_GATE_KEYS`, `_gate`, the null-only `verifier` rule.
- `S/_evaluation/combine_spec.py`: `_OPTIONAL_SPEC_KEYS` (+ `gate`), `_is_spec`.
- `S/report.py`: export `CombineGate`.
- New tests: `ET/test_combine_gate_words.py` (19 items), `ST/test_gate_words.py` (24 items).

### Pinned edits

- `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`:
  regenerated; adds `$defs.GateSpec` and `properties.gate` only.
- `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`:
  regenerated; adds `$defs.GateRecord`, `properties.gate`, `properties.verifier` only.
- `packages/screamingface/tests/public_surface_snapshot.json`: regenerated; `CombineGate` (export
  and class entry), `CombineEvidence.__init__` `gate`, `CombineEvidence.gate`.

### Test plan

- 15 PRD rows in PRD §7 order. CHAR: GR#1 (two functions, ET and ST; fixed lists L32 and L43,
  44 specs). RED: GR#3–GR#11, GR#17, VS#2, VS#3. PIN: GR#13, VS#1 (read the regenerated
  snapshots).
- Stubs in commit A: the Engine words (final), `GateSpec` and `GateRecord` unwired and without
  checks, the SDK aliases and a `CombineGate` stub without checks (`to_dict` raises
  `NotImplementedError`). Commit A: ET 18 failed / 1 passed, ST 23 failed / 1 passed.
- Oracles: fixture V of gate-decision §3 (agreement `0.6666666666666666`), the GD-3 / GD-4 /
  GD-D1 forms, the fixed rule messages of the unit spec.

### Acceptance

- A vote spec with `gate` parses on the Engine; a gate on another reducer, an explicit null, an
  undeclared name, a bad word, an agreement gate with `<` / `<=` or a threshold outside [0, 1]
  is `combine_spec_invalid` with a fixed message that echoes no value.
- The evidence writes `gate` after `declared` and before `result`, keys in record order; the
  invariants refuse mismatches on both sides; `verifier` is null only and never written.
- The SDK decodes and writes back every gate form byte for byte; `sf.report.CombineGate` exists.
- The 32 cases of L32 and the 44 specs of L43 keep their bytes and have no gate.
- Gates: append-only lists only the three pinned files; every other gate green; `repo` green.

### Deviations

- (pre-filled) D-1: GR-I1 is also checked on the evidence in this unit: a gate that did not run
  (`passed` null) goes with an abstained result (erd §4 GR-I1). The "reason other than
  `gate_not_met`" half comes with GR-I3 in unit 2.
- (pre-filled) D-2: the Engine `GateRecord` also checks the `observe` grammar (`GATE_OBSERVE`),
  and the SDK `CombineGate` checks it with the declared-name rule (`is_signal_name`), so the SDK
  also refuses `chosen:cost_usd`. The PRD names the grammar check only for the SDK.
- (pre-filled) D-3: GR#1 is two test functions (ET and ST) for one row. The L43 part reads each
  combine spec of a url4 file with `json.JSONDecoder().raw_decode` at each `{"extract":`, and
  checks `"gate" not in parse_spec(text).model_fields_set`, so the CHAR row passes before the
  change too.
- (pre-filled) D-4: an evidence `"gate": null` is accepted and not written back on both sides (the
  `cut` precedent). A spec `"gate": null` is refused on both sides.
- (pre-filled) D-5: GR#4 uses `rank_signal_spec(3, 2, "cost_usd", "min")` for the rank case;
  GR#5 adds a `bool` threshold case to the GR-E2 list.

### Notes for the review

- Interim gap: until unit 3, `Url4.to_python()` rebuilds a hand-written gated vote spec as an
  `sf.Vote` without its gate (the spec decoder accepts `gate` from this unit on). Unit 3 (GA#12a)
  closes it.
- Until unit 2 the Engine accepts a gate key and ignores it at run time; no released state has
  this.
- For unit 2: GR-I3 goes directly before the Engine call `_check_gate(self)` in
  `CombineEvidence._check`, and directly before the SDK call `_check_gate(selected_gate, ...)` in
  `CombineEvidence.__init__` (the local variable is `selected_gate`).
- The SDK aliases `GateCmp`, `GateBranch`, `GateOtherwise` live in `S/combine_evidence.py`. Unit 3
  may define its own `GateCmp` in `S/gate.py`; the two aliases do not conflict.

### Outcome

- **Status:** Done. Commit B is built and gated. The three pinned files are regenerated. The
  append-only check lists only those three files, as planned. Every other gate is green.
- **Actual files:** Commit B changes 7 source files: `E/combine/ports.py`, `E/combine/spec.py`,
  `E/combine/evidence.py`, `S/combine_evidence.py`, `S/_evaluation/combine_evidence.py`,
  `S/_evaluation/combine_spec.py`, `S/report.py`. It also changes the 3 pinned files: the two
  engine schema snapshots and `packages/screamingface/tests/public_surface_snapshot.json`. No test
  file is edited. No file under `.claude/test-change-approvals/` is touched.
- **Commits:** A `689eeffe4` (RED tests and stubs). B `5fc1c78c2` (code and pinned regeneration).
  C: this section and the overview errata E1.
- **Gates:**
  - Focused runs after B: ET `test_combine_gate_words.py` 19 passed. ST `test_gate_words.py` 24
    passed. Engine group of §9 254 passed. SDK group of §9 132 passed.
  - `screamingface-engine`, run 1: red only on the append-only check. The check lists
    `tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json` and
    `tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`. Run 2 with
    `--skip-append-only`: ALL GATES GREEN (ruff, ruff format, pyright, layering, pytest with
    coverage 80 percent).
  - `screamingface`, run 1: red only on the append-only check. The check lists
    `tests/public_surface_snapshot.json`. Run 2 with `--skip-append-only`: ALL GATES GREEN (ruff,
    ruff format, pyright, pytest with coverage 95 percent, notebooks, build, distribution).
  - `repo`, no flag: ALL GATES GREEN (append-only check passed).
  - Appendix E check printed `snapshot diff OK`. Appendix F check: the surface diff has 17
    insertions and 1 deletion, as the spec states.
- **RED log:** commit A (stubs and RED tests). ET: 1 passed (GR#1), 18 failed. ST: 1 passed
  (GR#1), 23 failed. Each failure is the reason of the spec §5 table: extra key `gate` or
  `verifier`, `DID NOT RAISE`, `unsupported field 'gate'`, `module 'screamingface.report' has no
  attribute 'CombineGate'`, a snapshot `None` (PIN). No ImportError, no NameError.
- **Flakes:** None seen in the runs of this unit. The known flaky tests (OME-1619) were not run
  alone, because no test failed outside the append-only check.
- **Deviations:**
  - Spec §9 names `tests/unit/test_combine_evidence.py`. This file is not in the tree. The focused
    engine run stopped with "file not found", and it ran again without that name (254 passed). The
    full engine gate ran every test file. The spec name is wrong. No code changed for it.
  - Appendix F of the unit spec shows the `CombineEvidence` hunk with an added `to_dict` tail. The
    real regenerated diff has the same added lines (the `gate` field, the `gate` argument, and the
    `CombineGate` class entry), with the stat the spec states. The regeneration tool wrote the file.
  - The restore step of §11 used `git checkout 62060ebec -- <the 7 source files>`. It stages the
    restore before the two patches are applied. Commit B includes the result.
  - Wisdom check: the implementer checked the diff against §2 and §5 by reading it. No separate
    design review ran in this unit.
  - The pre-filled deviations D-1 to D-5 apply as written.
- **Approval blobs:**
  - `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`
    base `b3acb2a5cd5c489c570a57384cd40fa5c9f30273` after `b62a7858ca4c9877398bf4cfaa2208ae178bb47e`
  - `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`
    base `406747a92a4c44d05aff27f0922e7582250cc31a` after `1cbdad39b71843479e77805e8448eadb3735b28f`
  - `packages/screamingface/tests/public_surface_snapshot.json`
    base `8b961b377cf44c46d7b4fc39a0fd596c53ba451f` after `e3cd603c7ea291b6085715788478a0152b3b8b6d`

### Review fixes (unit 1)

The review gave 10 MINOR findings. No finding is about behavior, so no RED test was added.

- **Applied:**
  - `S/combine_evidence.py`: `CombineEvidence.__init__` builds `tuple(chosen)` one time
    (`selected_chosen`) and uses it for `_result`, `_check_gate` and `values["chosen"]`. The
    behavior does not change. This is a small change to the Appendix B text.
  - Notes for the review: one line added for the Engine interim gap (until unit 2 the Engine
    accepts a gate key and ignores it at run time).
  - Outcome: the RED log line is wrapped at 100 columns.
- **Not applied (routed to the orchestrator or the owner):**
  - The three pinned files: the owner approves the blobs above. The blobs did not change in this
    fix.
  - One SDK home for `GateCmp`, `_GATE_CMPS` and `_gate_observe` (unit 3 must import them from
    `S/combine_evidence.py` or `S/_signals.py`). The unit 1 note that "the two aliases do not
    conflict" is replaced by this routing.
  - `GATE_OBSERVE` built from `DECLARED_NAME.pattern`: optional, and Appendix A was "apply
    exactly". It needs the orchestrator's consent.
  - The Engine and SDK `observe` strictness (D-2) and a possible "gate name is a key of `declared`"
    invariant: a unit 2 decision.
  - The GR-I5(b) message words ("that one member" against "that member"): no change now; make them
    the same if unit 2 touches them.
  - Spec §9 names `tests/unit/test_combine_evidence.py`, which is not in the tree: correct the
    focused-run list for the later units.
  - `passed` and `branch` are a one-to-one pair while `GateBranch` has two values: an owner
    decision.
- **Gates after the fixes (vs `4e622af75`, one stack at a time):**
  - `screamingface-engine`: red only on the append-only check (the two pinned schema files). With
    `--skip-append-only`: ALL GATES GREEN.
  - `screamingface`: red only on the append-only check (`tests/public_surface_snapshot.json`,
    pinned). With `--skip-append-only`: ALL GATES GREEN.
  - `repo`, no flag: ALL GATES GREEN.
- **Flakes:** none seen.

## Unit 2: gate decision (`gate-decision`)

### Intent

PRD `gate-decision` rows GD#1–21 and PRD `gate-record` rows GR#2, GR#12, GR#14, GR#15, GR#16
(ans:Q1–Q3, P4, P8, P10–P14, P18–P21). The vote gate chooses and records: after the select step,
the Engine core computes the gate number (agreement, `chosen:<name>`, `mean:<name>`), compares it
with the threshold, and takes the majority or the fallback (abstain with `gate_not_met`, the
`fallback_judge` label member, or the `fallback_writer` text). The evidence `gate` record holds the
number, the comparison and the branch. The majority branch never reads a fallback reply (FB-I1). A
vote with no answer does not run the gate (GR-I1). The word `gate_not_met` joins the abstain words
on both sides, with GR-I3. The contract fixture gets five gate cases (32 → 37).

### Planned changes

- `E/combine/ports.py`: `gate_not_met` in `AbstainReason`, `AnswerReason` (last), `ABSTAIN_REASONS`;
  `parse_label` and `_LABEL_INVALID` moved here from the judge plugin; `judge_reply(..., *, key="judge")`.
- `E/combine/operators/judge.py`: imports `parse_label` from ports, keeps it in `__all__`; docstring.
- `E/combine/spec.py`: `_SIGNAL` accepts `fallback_judge`, `fallback_writer` (one literal).
- New `E/combine/gate.py` (pure): `observed_number`, `passes`, `fallback_label`, `fallback_text`,
  `check_fallback_signals`, `FALLBACK_JUDGE`, `FALLBACK_WRITER`.
- `E/combine/endpoint.py`: `check_fallback_signals` after `parse_context`; `_decide` → new `_choose`
  → new `_gated` → new `_fallback`; new `_kept`, `_not_run`, `_presentation_order`; `_abstain` and
  `_evidence` get keyword `selection` / `gate`; the chosen / built / presentation-order rules;
  module INVARIANT and `_decide` docstrings.
- `E/combine/evidence.py`: GR-I3 (`_gate_reason_holds`), first among the gate rules.
- `S/answer.py`: `gate_not_met` in `AbstainReason` and `AnswerReason`.
- `S/combine_evidence.py`: GR-I3 (`_gate_reason`) in `CombineEvidence.__init__`.
- Tests: new `ET/test_combine_gate.py`; appends to `ET/test_combine_gate_words.py`,
  `ST/test_gate_words.py`, `ET/test_combine_evidence_contract_fixture.py`,
  `ST/test_combine_evidence_contract.py`.

### Pinned edits

`ET/test_combine_pick_output.py` (:341-343, :352), `ET/test_combine_evidence_words.py` (:320 +1),
`ST/test_pick_output.py` (:250, :254 +1), `ST/test_evidence_words.py` (:373, :460, :466 +1),
`ST/test_frozen_record_fields.py` (:184 32 → 37), and the regenerated
`ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`,
`ST/data/schemas/screamingface.answer.v1.json`, `ET/data/combine_contract/evidence_cases.json`.
Append-only, not flagged: `ET/test_combine_evidence_contract_fixture.py`,
`ST/test_combine_evidence_contract.py`.

### Test plan

- 26 rows (GD 21, GR 5). CHAR: GD#1. PIN: GD#19, GR#15. RED: the others. Commit A changes no
  source file: unit 1's endpoint ignores the gate, the base `_SIGNAL` refuses `fallback_*`, and the
  word is absent, so each row fails on its behavior, not on an import.
- Expected RED: `ET/test_combine_gate.py` 25 items, 1 passed (GD#1), 24 failed.

### Acceptance

- Fixture V `{agreement,>=,0.6,abstain}`: output `"A"`, gate passed / majority, the rest of the
  evidence equals the ungated bytes.
- Fixture V `{agreement,>=,0.7,abstain}`: output `""`, evidence equals `GATE_ABSTAIN_WIRE`
  (`gate_not_met`, `chosen []`, tally / agreement / tie kept).
- Judge fallback `" member_3\n"`: output `"B"`, judge reading recorded, presentation order author.
- Writer fallback `"C written"`: output `"C written"`, value `"c written"`, built.
- The majority branch gives the same bytes with no reply, a good reply and a bad reply.
- `evidence_cases.json` has 37 cases; the 32 old cases keep their bytes.
- Gates: `screamingface-engine`, `screamingface`, `repo` green (append-only offenders = §8 files only).

### Deviations

- `_gated` takes the narrowed `gate: GateSpec` as its first parameter (the PRD signature has no
  `gate`), and a new `_choose` holds today's answer path, so `_decide` keeps 3 returns (ruff
  `max-returns = 3`). New `_fallback` for the same reason.
- The trace `agreement` and `tie` fields are set in `_gated` before the branch, so a gate abstain
  logs them (GD-D8).
- The SDK GR-I3 check is in `CombineEvidence.__init__` (the class has a hand-written `__init__`;
  the PRD says `__post_init__`). GR-I3 runs first among the gate rules on both sides, so one message
  names it.
- GR#16 is two test functions, one per side, counted as one row. GR#2 is on the Engine side; the
  SDK side of the word is GR#12.
- `ST/test_evidence_words.py`: the 12 → 13 count is on line 373 (plan: 372).
- The GD#19 test function is in `ET/test_combine_gate.py`.
- RED build: the spec §5 text says "25 items, 24 failed" for `ET/test_combine_gate.py`. The file
  has 26 items (the table has 21 rows; GD#11, GD#12 and GD#13 are parametrized into 8 items).
  The run gave 1 passed (GD#1) and 25 failed. Every failure has the reason of the §5 table.
- RED build: `WEIGHTED` in `ET/test_combine_gate.py` is annotated `dict[str, Any]`. Pyright reads
  `**WEIGHTED` as an argument for `member_count` and fails without it. A typing change only; no
  value changed.
- RED build: four section header comments are cut to 100 columns (ruff E501). No test changed.
- RED build: the SDK GR#16 positive control fails with `ExecutionError` (the decoder reads the
  unknown word), not with `ValueError`. The row still fails for the right reason.
- RED build: pyright reports 2 errors in `ET/test_combine_gate_words.py` (GR#2, lines 766-767)
  and 2 errors in `ST/test_gate_words.py` (GR#12, lines 541 and 544). Each is the unknown word
  `gate_not_met` in a `Literal` type. The word enters with commit B, so these clear in B.
- Build: the GR-I3 check of §2.6 is the first line of `_check_gate`, not a separate call in
  `CombineEvidence._check`. `_check` with the extra call had 9 branches (ruff C901 and PLR0912
  allow 8 and 7). `_check_gate` is called by `_check`, so GR-I3 is still the first gate rule and
  still runs before GR-I1, GR-I4 and GR-I5. Its docstring names GR-I3.
- Build: the SDK GR-I3 call (`_gate_reason`) is placed as the spec says: before `_check_gate` in
  `CombineEvidence.__init__`, and the helper sits after `_result`.
- Build: `ruff format` reflowed `endpoint.py`, `evidence.py` and the SDK files. No test changed.

### Notes for the review

- FB-I1: grep shows `fallback_judge` / `fallback_writer` read only in `combine/gate.py`.
- C9: `combine/gate.py` imports only the standard library, `combine.ports`, `combine.spec`.

### Outcome

- **Status:** Done. Commit B is built and gated. The engine and SDK data snapshots and the
  contract fixture are regenerated. The append-only check lists only the pinned files of spec §8
  and the unit 1 pinned files. Every other gate is green.
- **Actual files:** Commit B changes 12 files (the ledger is the 12th): the 11 source and data files: `E/combine/gate.py` (new),
  `E/combine/endpoint.py`, `E/combine/evidence.py`, `E/combine/ports.py`, `E/combine/spec.py`,
  `E/combine/operators/judge.py`, `S/answer.py`, `S/combine_evidence.py`, and the regenerated
  data files `ET/data/combine_contract/evidence_cases.json`,
  `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` and
  `ST/data/schemas/screamingface.answer.v1.json`. No test file is edited in commit B. No file under
  `.claude/test-change-approvals/` is touched.
- **Commits:** A `bf4ad7e9f` (RED tests, the pinned test edits of spec §8 items 1-5, the ledger
  section). B: `feat(e4b): the vote gate chooses and records (part 5 unit 2)`. C: the overview
  errata for unit 2, `docs(e4b): record the E4b part 5 unit 2 build errata`.
- **Gates:**
  - Focused runs before the gates. Engine: `test_combine_gate.py`, `test_combine_gate_words.py`,
    the contract fixture, the pick and words tests, the wire schema freeze, the judge, endpoint,
    abstain, declared-signal and exclusion tests: 318 passed. SDK: `test_gate_words.py`, the
    contract, pick, words, frozen-field, exclusion, agreement and signal-key tests: 156 passed.
  - `screamingface-engine`, run 1 with base `4e622af75`: red only on the append-only check. The
    check lists `tests/unit/data/combine_contract/evidence_cases.json`,
    `tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`,
    `tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json` (unit 1 pinned),
    `tests/unit/test_combine_evidence_words.py` and `tests/unit/test_combine_pick_output.py`.
    Run 2 with `--skip-append-only`: ALL GATES GREEN (ruff, ruff format, pyright, layering, pytest
    with coverage 80 percent).
  - `screamingface`, run 1 with base `4e622af75`: red only on the append-only check. The check
    lists `tests/data/schemas/screamingface.answer.v1.json`, `tests/public_surface_snapshot.json`
    (unit 1 pinned), `tests/test_evidence_words.py`, `tests/test_frozen_record_fields.py` and
    `tests/test_pick_output.py`. Run 2 with `--skip-append-only`: ALL GATES GREEN (ruff, ruff
    format, pyright, pytest with coverage 95 percent, notebooks, build, distribution).
  - `repo`, base `4e622af75`, no flag: ALL GATES GREEN (append-only check passed).
  - The spec §9 step 7 also names the base `<unit 1 tip>` (`abee4d5cf`). This unit ran only the
    base `4e622af75`, the base the build task named.
- **RED log:** the RED log of commit A is in the section above. Commit B did not re-run it.
- **Flakes:** None seen. No test failed outside the append-only check, so the three known flaky
  tests (OME-1619) were not run alone.
- **Pinned edits made:** Commit A holds the §8 test edits (items 1-5). Commit B holds the data
  regenerations of §8 items 6-8: the engine evidence v1 snapshot (two words: `gate_not_met` in
  the two enum lists), the SDK `answer.v1` snapshot (two words: `gate_not_met` in
  `abstain_reason` and `reason`), and `evidence_cases.json` (five cases appended; the script of
  spec §9 step 3 showed the 32 old cases keep their bytes). No other pinned file changed.

### Review fixes (unit 2)

The review gave one MAJOR finding and six MINOR findings. The MAJOR finding is about behavior, so
RED came first.

- **MAJOR, applied (RED first).** A `mean:<n>` gate raised a bare `OverflowError` when the exact
  sum of the member values passed the float range. Each value was finite, so the Case crashed
  with an error that is not a `CombineError`. The RED test
  `test_mean_signal_gate_stays_finite_when_the_exact_sum_overflows` failed with that error. The
  fix in `E/combine/gate.py` (`_mean`): `math.fsum` of the values over their count, and when that
  overflows, `math.fsum` of the quotients. The test passes. The PRD gap is erratum E6 in
  `docs/spec/2026-10-16-e4b-gate-record/00-overview.md`.
- **MINOR, applied.** `_gate_record(gate, observed, passed)` in `E/combine/endpoint.py` builds
  the record for `_gated` and `_not_run`. No behavior change.
- **MINOR, applied.** The ledger Outcome of unit 2 counts 12 files, not 11 (the ledger is the 12th).
- **MINOR, not applied (orchestrator).** `_choose` and the passed branch of `_gated` repeat the
  answer path. The shape is the spec-dictated E2 split. The owner decides whether to merge them.
- **MINOR, not applied (orchestrator).** `_fallback` uses `cast("str", reading.parsed)` and
  rebinds `reduction`. Spec text. No change.
- **MINOR, not applied (open question).** `observed_number` with `chosen:<n>` reads
  `selection.chosen[0]`. A vote with an output-building select has no chosen member, so the read
  raises `IndexError`. The built-in vote selects (`first_holder`, `max_weight_holder`) never do
  this. The fix needs one decision: return None (the comparison is false), or refuse the pair at
  spec check time.
- **MINOR, applied.** Gates were run at both bases named in spec §9 step 7 (see Gates below).
- **Pinned edits.** No pinned file changed in this fix. The pinned set is the same as in Outcome
  of unit 2.

### Gates (unit 2 review fixes)

- Base `4e622af75`:
  - `screamingface-engine`: run 1 red only on the append-only check (the unit 2 pinned files
    only). Run 2 with `--skip-append-only`: ALL GATES GREEN.
  - `screamingface`: run 1 red only on the append-only check (the unit 2 pinned files and the
    unit 1 pinned `public_surface_snapshot.json`). Run 2 with `--skip-append-only`: ALL GATES
    GREEN.
  - `repo`: ALL GATES GREEN, append-only check passed.
- Base `abee4d5cf` (unit 1 tip, spec §9 step 7):
  - `screamingface-engine`: run 1 red only on the append-only check (the four unit 2 pinned
    files). Run 2 with `--skip-append-only`: ALL GATES GREEN.
  - `screamingface`: run 1 red only on the append-only check (the four unit 2 pinned files).
    Run 2 with `--skip-append-only`: ALL GATES GREEN.
  - `repo`: ALL GATES GREEN, append-only check passed.
- Flakes: none seen.

### Orchestrator fix (unit 2, 2026-10-16)

- The second review left one MAJOR: the `math.fsum` of the quotients can still overflow (three
  values of `sys.float_info.max`). Fix: on `OverflowError` the mean is the exact `Fraction` mean,
  rounded to a float (erratum E6, updated).
- The open MINOR about `chosen:<n>` with no chosen member is closed: the observed number is None,
  so the fallback answers (erratum E7).
- RED first: `test_mean_of_values_at_the_float_limit_is_finite` (3, 7 and 1000 members) and
  `test_chosen_signal_with_no_chosen_member_is_missing` failed with `OverflowError` and
  `IndexError`, then passed after the fix. The review comment "(review fix)" in `gate.py` is now a
  `WHY` comment.

## Unit 3: gate-api-core (`sf.Gate`, `sf.Vote(gate=, verify=)`)

### Intent

PRD `gate-api` rows GA#1, GA#2, GA#5–9, GA#12a, GA#17a, GA#18a, GA#19, GA#20 and PRD
`verifier-slot` rows VS#4–6 (ans:Q1–Q4; P1, P3, P4, P7, P15, P17). The SDK gets the public class
`sf.Gate(observe, cmp, threshold, *, otherwise="abstain")` with every constructor check, its repr
and Python form. `sf.Vote` gets `gate=` and the reserved `verify=None`. The combine spec gets the
key `gate`. `sf.Fusion` refuses a gate that reads an undeclared name before any call.
`Url4.to_python()` rebuilds a gate with no fallback call. Two SDK-compiled fixtures (abstain,
verbalized) run offline in the Engine world. The judge and writer fallback calls are unit 4:
`Gate._signal_call` raises `NotImplementedError` for them here.

### Planned changes

- New `S/gate.py`: `Gate`, `GateCmp`; helpers `_observe`, `_cmp`, `_threshold`,
  `_check_agreement`, `_otherwise`, `_otherwise_word`, `_python_form`.
- `S/reducer.py`: `_ReducerPlan.gate`; `Vote` fields `gate`, `verify`; `Vote.__init__(...,
  gate=None, verify=None)`; `_vote_gate`, `_check_verify`, `_recovered_gate`, `_GATE_KEYS`;
  `_vote_plan(..., gate=None)`; `Vote._plan`, `_from_spec_parts`, `_render`.
- `S/fusion.py`: `_check_gate_name` called from `_declared`; docstring sentence.
- `S/_evaluation/combine_spec.py`: `combine_spec_text` writes `gate`.
- `S/__init__.py`: export `Gate`.
- New tests `ST/test_gate_api.py` (13 tests), `ST/test_gate_contract_fixtures.py` (2 ids),
  `ET/test_combine_gate_run.py` (2 ids). New data
  `ET/data/combine_contract/gate_abstain_vote_candidate.url4`,
  `ET/data/combine_contract/gate_verbalized_vote_candidate.url4`.

### Pinned edits

- `packages/screamingface/tests/public_surface_snapshot.json` (regenerated with
  `UPDATE_SURFACE_SNAPSHOT=1`): `Gate` in `__all__` and `exports`; `Vote.__init__` gains
  `gate: 'Gate | None' = None, verify: 'None' = None`; `Vote` members `gate`, `verify`.

### Test plan

- 15 rows: CHAR GA#1; RED GA#2, 5, 6, 7, 8, 9, 12a, 17a, 18a, 19, VS#4, 5, 6; PIN GA#20 (the
  regenerated snapshot plus one introspection test).
- Stubs (commit A): `S/gate.py` with the exact `Gate.__init__` signature whose body raises
  `NotImplementedError`; `sf.Gate` exported. `sf.Vote` gets no new keyword in commit A, so the
  `gate=` / `verify=` rows fail on the missing keyword. Expected RED: SDK `14 failed, 1 passed`
  for the two new files; `test_public_surface_matches_the_committed_snapshot` fails; Engine
  `2 failed`.
- Oracles: hand-derived spec texts (unit spec §3.2), the PRD messages, fixture V numbers
  (agreement `0.6666666666666666`), GD-2 and GD-5 for the Engine runs.

### Acceptance

- The 15 rows pass. GA#1 passes before and after the change.
- The snapshot diff is only the three changes of the pinned edit.
- `git diff U2 --stat` on the two test folders lists only the new files and the snapshot.
- Gates: `screamingface-engine`, `screamingface`, `repo` green, except the append-only check
  against `4e622af75`, which lists only the pinned files of units 1–3; green with
  `--skip-append-only`.

### Deviations

- D-1 (GA-5 oracle): "a recipe whose repr equals the original's" cannot hold literally: the url4
  rebuild keeps the pinned operator ids (`extract='last_line@1', normalize='text@1'`, part 3
  erratum E9). GA#12a compares the rebuilt repr with a hand-written literal that holds the `@1`
  ids, checks that the rebuilt gate equals the original gate, and checks the byte-equal recompile.
- D-2 (GA#1 method): "recompiles byte-equal" uses the operator ids that each url4 pins
  (`_OperatorCatalog.from_pinned`), and for `corrective_vote_candidate.url4` the IFEval check
  route the url4 holds (`feedback_intent="feedback"`, as its drift guard). Checked on
  `62060ebec`: 43 of 43 equal.
- D-3 (plan §2 file split): `_vote_plan` appends the gate fallback call after the judge call in
  this unit, not in unit 4. So a judge or model fallback fails loudly (`NotImplementedError` at
  plan time) and never compiles a spec with `otherwise: "judge"` and no call. Unit 4 only fills
  `Gate._signal_call` and tests the order (GA#15).
- D-4 (PRD constructor table): the TypeError row names "a route string", but a route string is a
  `str`, which the ValueError row covers. Built rule: every `str` other than `"abstain"` →
  ValueError; every other object that is not an `sf.Judge` or an `sf.Model` → TypeError.
- D-5 (addition): `Gate.__hash__ = None`, as `sf.Vote`: a gate may hold an `sf.Model`, which is
  unhashable.
- D-6 (addition): GA#20 also gets a small introspection test in `ST/test_gate_api.py`; it checks
  names, kinds and defaults only, so a later signature change does not turn it red.
- D-7 (helpers): `_observe`, `_cmp`, `_threshold`, `_check_agreement`, `_otherwise`,
  `_otherwise_word`, `_python_form`, `_vote_gate`, `_check_verify`, `_recovered_gate`,
  `_check_gate_name` are private helpers the PRD does not name. They keep the ruff caps
  (max-branches 7, max-returns 3, mccabe 8).
- D-8 (open, commit A): the unit 2 review routed "one SDK home for `GateCmp`, `_GATE_CMPS` and
  `_gate_observe`" to this unit. The unit spec §2.1 still defines `type GateCmp` in `S/gate.py`
  and `_observe` there. Commit A follows §2.2. The owner or the orchestrator decides the home
  before commit B.

### Outcome

- **Status:** Done. Commit B is built and gated. The three stacks pass every gate except the
  append-only check. That check lists only files that units 1 to 3 changed on purpose (the
  pinned files). Each stack is green with `--skip-append-only`.
- **Actual files:** Commit B changes 9 files. The source files are `S/gate.py` (the full module
  of spec §2.1), `S/reducer.py` (§2.4), `S/fusion.py` (§2.5) and `S/_evaluation/combine_spec.py`
  (§2.6). The data files are the two fixtures `ET/data/combine_contract/gate_abstain_vote_candidate.url4`
  and `ET/data/combine_contract/gate_verbalized_vote_candidate.url4` (written by the SDK, spec §9),
  and the PINNED `ST/public_surface_snapshot.json`. The test file `ST/test_gate_api.py` gets one
  assert edit (see Deviations). The ledger is the 9th file. No Engine code changed. No file under
  `.claude/test-change-approvals/` was touched.
- **Commits:** A = `70a483af6` (RED tests and stubs). B = the commit that adds this text (its sha is
  in `git log`). C = none (spec §11).
- **U2 (unit 2 tip):** `d88bec796`. `git diff d88bec796 --stat` on the two test folders lists only
  the new unit 3 test files, the new fixtures (untracked until commit B) and the PINNED snapshot.
- **RED log:** Before the code, the RED run gave `13 passed, 2 failed` for `tests/test_gate_api.py`
  and `tests/test_gate_contract_fixtures.py`. The 2 failures were the missing fixture files
  (`AssertionError`), as the spec expects. The snapshot was regenerated after the code.
- **Gates:** Focused runs after commit B's code. SDK: `test_gate_api.py`, `test_gate_contract_fixtures.py`,
  `test_public_surface.py`: 23 passed. The related SDK set of spec §9: 259 passed. Engine: the four
  gate and verbalized run tests: 55 passed.
  - `screamingface-engine`, base `4e622af75`: red only on the append-only check. It lists
    `tests/unit/data/combine_contract/evidence_cases.json`,
    `tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`,
    `tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`,
    `tests/unit/test_combine_evidence_words.py` and `tests/unit/test_combine_pick_output.py`. All five
    are units 1 and 2 pinned edits. With `--skip-append-only`: ALL GATES GREEN (ruff check, ruff
    format, pyright, layering, pytest with coverage).
  - `screamingface`, base `4e622af75`: red only on the append-only check. It lists
    `tests/data/schemas/screamingface.answer.v1.json`, `tests/public_surface_snapshot.json` (the PINNED
    edit of this unit), `tests/test_evidence_words.py`, `tests/test_frozen_record_fields.py` and
    `tests/test_pick_output.py`. The last four are units 1 and 2 pinned edits. With
    `--skip-append-only`: ALL GATES GREEN (ruff check, ruff format, pyright, pytest with coverage 95,
    notebooks, build, distribution check).
  - `repo`, base `4e622af75`: ALL GATES GREEN, the append-only check included.
- **Flakes:** None seen. The OME-1619 tests ran in the stacks that reached pytest, and they passed.
- **Deviations (build):**
  - D-9 (test fix, pyright): `ST/test_gate_api.py` line 197 read `assert "signals" not in context`.
    `RelExpr.context` has type `str | None`, so pyright failed the gate (`reportOperatorIssue`). The
    edit is `assert context is not None and "signals" not in context`. The previous assert already
    shows that the context is a string, so the meaning is the same. This is the only edit to a test
    that commit `70a483af6` added. It is not a PINNED edit.
  - D-8 (still open): the unit 2 review asked for one SDK home for `GateCmp`, `_GATE_CMPS` and
    `_gate_observe`. This commit follows spec §2.1: `GateCmp` and `_observe` live in `S/gate.py`.
    `S/combine_evidence.py` keeps its own `GateCmp`, `_GATE_CMPS` and `_gate_observe`. Two homes
    exist. The owner or the orchestrator must still decide the single home.
  - Format: `ruff format` wrapped two lines (in `S/gate.py` and `S/reducer.py`). No meaning changed.
  - PINNED snapshot: the diff has exactly the three changes of spec §8 (`Gate` in `__all__`, `Gate`
    in `exports`, and the `Vote.__init__` and members lines).

## Unit 4: the judge and writer fallback calls (`gate-api-fallback`)

### Intent

PRD `gate-api`, rows GA#3, GA#4, GA#10, GA#11, GA#12b, GA#13 to GA#16, GA#17b and GA#18b (ans:Q1,
ans:Q3, P5 to P7, P17, FC-I1, FC-I3, C2, C6, C7). An `sf.Gate` with an `sf.Judge(returns="label")`
or an `sf.Model` fallback compiles to one more model call. The call is the source `judge_N` or
`writer_N`. It has the operation `{fusion} fallback judge` (kind `judge`) or `{fusion} fallback
write` (kind `writer`), one rider signal, and the context key `fallback_judge` or
`fallback_writer`. `Url4.to_python()` rebuilds the gate with its fallback. A hand-edited url4
cannot rebuild. Two SDK-compiled fixtures run offline in the Engine world, and the gateway gets
four requests: the fallback call runs on every Case (ans:Q1).

### Planned changes

- `S/gate.py`: `Gate._signal_call` returns `replace(judge._signal_call(), key="fallback_judge")`
  for an `sf.Judge`, and `_ModelSignal("fallback_writer", ...)` for an `sf.Model`. The default
  prompt is `DEFAULT_SYNTHESIS_PROMPT`.
- `S/reducer.py`: constants `_FALLBACK_JUDGE_KEY` and `_FALLBACK_WRITER_KEY`; `_vote_plan`
  signal order; `_rebuilt_fallback` and `_rebuilt_gate`; the signal split in `Vote._rebuild`;
  `Vote._from_spec_parts` takes the fallback call.
- `S/_evaluation/topology.py`: `_FALLBACK_ROLES`, `_signal_role`, `_decode_signal` (FC-I3) and
  `_operation_shape`.
- `S/_evaluation/reducer_signals.py`: `_signal_call_role` (FC-I3).
- `S/url4.py`: `_model_signal` (the outputs form of the fallback judge) and `_rebuilt_reducer`
  (no `sf.Reduce` fallback for a gated spec).
- Tests appended: `ST/test_gate_api.py`, `ST/test_gate_contract_fixtures.py` and
  `ET/test_combine_gate_run.py`.
- New fixtures: `ET/data/combine_contract/gate_judge_vote_candidate.url4` and
  `ET/data/combine_contract/gate_writer_vote_candidate.url4`. The SDK writes both.
- No Engine source change. No public name.

### Pinned edits

None. The three test files are new since `4e622af75` (unit 3 created them). The two fixtures are
new files.

### Test plan

- 11 PRD rows, all RED: GA#3, GA#4, GA#10 (2 items), GA#11 (2 items), GA#12b (3 items), GA#13
  (4 items and 1 function), GA#14, GA#15, GA#16, GA#17b (2 items), GA#18b (2 items).
- RED stub: the `NotImplementedError` of unit 3 in `Gate._signal_call`. Commit A adds no stub.
- Expected RED: every new item fails. Only
  `test_hand_edited_gate_urls_cannot_rebuild[judge_gate_without_its_call]` may pass, because unit 3
  already refuses a judge gate with no call.
- Invariants: FC-I1 (one fallback call, after the weights judge call), FC-I2 (the combine
  operation depends on it), FC-I3 (a projection only for `writer_<field>`), C7 (the rebuild split,
  and no `sf.Reduce` fallback for a gate).

### Acceptance

- The judge fixture compiles to `judge_1` on `/prov/judge` with the label template and the
  rubric. The context has `signals: {fallback_judge: '$judge_1'}`. The operation is
  `vote fallback judge`.
- The writer fixture compiles to `writer_1` with no projection. The operation is
  `vote fallback write`.
- Each gated vote with a fallback rebuilds from its url4 and recompiles to the same bytes.
- The Engine world runs each fixture. It makes four requests. The output is `"B"` (judge) or
  `"C written"` (writer). The gate record is `{agreement, 0.6666666666666666, >=, 0.7, false,
  fallback, <otherwise>}`.
- `screamingface-engine`, `screamingface` and `repo` gates are green. The append-only check
  names only the plan section 6 files of units 1 to 3.

### Deviations

- D-1 (planner): the PRD GA-5 says the rebuilt recipe has the same `repr` as the original. For a
  default `sf.Vote(...)` the rebuilt steps come back pinned (`extract='last_line@1',
  normalize='text@1'`), as for every rebuilt vote since E4a, so the whole-recipe `repr` differs.
  GA#12b checks the byte-equal recompile, the gate equality and the gate `repr` instead (the same
  check as GA#12a).
- D-2 (planner): GA#13 adds a fifth case, two fallback calls on one vote (FC-I1), checked on
  `Vote._rebuild` directly.
- D-3 (test mechanics, RED): the spec table of `_fb_hand_edits` built all four recipes at
  once. Then every hand-edit case failed at the build of the judge fallback (`NotImplementedError`),
  and `gate_on_a_median` never reached its "DID NOT RAISE" check. Each case now holds a recipe
  builder (`lambda`), so each case runs only its own compile. The assertions do not change.
- D-4 (RED reasons observed): GA#13 `judge_gate_without_its_call` fails with "DID NOT RAISE",
  not as a pass: unit 3 does not refuse a judge gate whose call is missing. This is the planned
  failure of C7. `test_hand_edited_gate_vote_with_two_fallback_calls_cannot_rebuild` fails with
  `NotImplementedError`, not with "cannot rebuild": `combine_spec_text` plans the judge fallback
  first. This is the unit 3 stub, as the table of section 6 names for the judge cases.

### Outcome

- **Status:** Done. Commit B is built and gated. Every gate is green. Only the append-only
  check is red for two stacks, and every file it names is on the units 1 and 2 pinned list. This
  unit adds no pinned edit.
- **Actual files:** Commit B changes 5 source files: `S/gate.py`, `S/reducer.py`,
  `S/url4.py`, `S/_evaluation/topology.py`, `S/_evaluation/reducer_signals.py`. It adds 2 url4
  fixtures: `ET/data/combine_contract/gate_judge_vote_candidate.url4` and
  `ET/data/combine_contract/gate_writer_vote_candidate.url4`. It edits one RED test function
  annotation (see Deviations D-5). No Engine source file changed. No public name changed.
- **Commits:** A `7e59358ee` (RED tests). B `fabd36c2e` (code, fixtures, one annotation). C: this
  section.
- **Start commit:** `ba8ed4b65` (unit 3 tip).
- - **RED log (focused runs, commit A):**
  - SDK `tests/test_gate_api.py` and `tests/test_gate_contract_fixtures.py`: 15 passed,
    19 failed. Failure reasons: 16 items raise `NotImplementedError` from
    `S/gate.py` line 86 (the unit 3 stub). GA#16 `test_signal_key_bind_accepts_the_fallback_keys`
    fails with `AssertionError` (`_signal_role` gives `None` for both fallback keys). GA#17b
    (2 items) fails with `AssertionError`: the fixture file is missing. Unit 3 items: all pass.
    GA#13 `judge_gate_without_its_call` fails with `DID NOT RAISE ValueError` (D-4).
  - ET `tests/unit/test_combine_gate_run.py`: 2 passed (unit 3), 2 failed (GA#18b, the
    fixture file is missing: `AssertionError`, as planned).
  - No ImportError and no collection error.
- **Gates (run in order, one stack at a time, from the worktree root, base `4e622af75`):**
  - `screamingface-engine`: run 1 red only on the append-only check. The check lists 5 files:
    `tests/unit/data/combine_contract/evidence_cases.json`,
    `tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`,
    `tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`,
    `tests/unit/test_combine_evidence_words.py`, `tests/unit/test_combine_pick_output.py`. All 5
    are units 1 and 2 pinned files (plan §6). Run 2 with `--skip-append-only`: ALL GATES GREEN
    (ruff, ruff format, pyright, layering, pytest with coverage 80 percent).
  - `screamingface`: run 1 red only on the append-only check. The check lists 5 files:
    `tests/data/schemas/screamingface.answer.v1.json`, `tests/public_surface_snapshot.json`,
    `tests/test_evidence_words.py`, `tests/test_frozen_record_fields.py`,
    `tests/test_pick_output.py`. All 5 are units 1 and 2 pinned files. Run 2 with
    `--skip-append-only` failed once at pyright (D-5). After the D-5 fix, run 3 with
    `--skip-append-only`: ALL GATES GREEN (ruff, ruff format, pyright, pytest with coverage 95
    percent, notebooks, build, distribution).
  - `repo`: run 1, no flag: ALL GATES GREEN (append-only check passed).
  - Focused runs after B: SDK `tests/test_gate_api.py`, `tests/test_gate_contract_fixtures.py`,
    `tests/unit/test_signal_key_conformance.py`, `tests/test_judge_url4_round_trip.py`,
    `tests/test_judge_quorum.py`, `tests/test_judge_reducer.py`,
    `tests/test_merge_writer_compile.py`, `tests/test_reducer_url4_round_trip.py`,
    `tests/test_quorum_url4_contract_fixtures.py`, `tests/test_verbalized_contract_fixture.py`,
    `tests/test_public_surface.py`: 97 passed, 0 failed. Engine
    `tests/unit/test_combine_gate_run.py` and `tests/unit/test_sdk_candidate_contracts.py`: 8
    passed. The two GA#18b items (`judge`, `writer`) pass.
  - Lint after B: `ruff check` and `ruff format` pass on the touched SDK source files.
- **Flakes:** None seen. The known flaky tests (OME-1619) did not fail, so none was rerun alone.
- **Deviations:**
  - D-1 and D-2 (planner): see the RED section above.
  - D-3 and D-4 (RED build): see the RED section above.
  - D-5 (test edit, a real type bug): `tests/test_gate_api.py`, helper `_fb_fusion`, parameter
    `quorum` changed from `int | str` to `Any`. Pyright rejected the annotation, because
    `sf.Fusion` takes `int | Literal["all"]`. No assertion changed. The gate failed on this
    line only.
  - D-6 (lint): `S/_evaluation/topology.py` `_signal_role` and `S/url4.py` `_rebuilt_reducer` have
    4 returns each, so ruff PLR0911 (max 3) fails. Each function keeps the code of the spec and
    gets `# noqa: PLR0911` on its `def` line. This form has precedent in the repo
    (`_runtime/cli.py`, `tests/test_connection_panel.py`).
  - D-7 (no change): spec §3.1 `_vote_plan` already had the judge-then-fallback order from unit 3.
    Nothing changed there.
  - D-8 (review): no separate design review ran in this unit. The unit was checked against
    spec §3, §7 and §8 by reading the diff. The orchestrator runs the design review.
- **Pinned edits:** none.

## Unit 5: show the gate in the report (`gate-display`)

### Intent

PRD `gate-display`, rows GS#1–12 (ans:Q1 "records the comparison and the branch"; P16; part 4
ans:Q1–Q3 surfaces and number format). The Case pane Combine section of a gated vote gets one gate
chip right after the agreement chip: `gate · {observe} {cmp} {threshold} · observed {observed} ·
{verdict}` (verdict `majority`, `fallback · {otherwise}` or `not run`; a missing number is an em
dash with its reason). The run summary of a gated step gets one line between its heading and its
table: `gate · majority {m} of {N} · fallback {f} of {N}` (+ ` · not run {r} of {N}`). Rule J4: a
gate that took its fallback judge counts as a judge read, so the judge chip and the trace
`judge_model` name the fallback judge (exactly one judge operation, as before). The export already
holds `operations[].combine.gate`; no export, trace or schema change. An ungated step keeps its
bytes.

### Planned changes

- `S/_ui/combine_view.py`: constants `_GATE_NOT_RUN`, `_GATE_NO_NUMBER`; `_gate_chip`,
  `_gate_verdict`; one `_chips` item after the agreement chip; `_StepSummary` fields `gated`,
  `majority`, `fallback`, `not_run` and the method `_add_gate`; `_gate_line`; `_summary_html`
  returns `heading + _gate_line(step) + _table(...)`.
- `S/_case_views.py`: `_reads_judge` rule J4.
- New test file `ST/test_gate_display.py` (GS#1–12). It reads
  `COMBINE_CONTRACT / "evidence_cases.json"` under `requires_engine_app` and builds each Case by
  hand; it never uses `_answer_fixtures.fixture_case` and never edits
  `ST/data/combine_evidence_cases.json`.

### Pinned edits

None.

### Test plan

- 12 PRD rows in the PRD §7 order. CHAR: GS#1 (the 32 L32 cases, sha256 of section + summary
  taken on the `4e622af75` SDK), GS#11 (the export; "no change expected"). RED: GS#2–10, GS#12.
- No stub: the tests import no new name. Each RED row fails on an assertion.
- Every chip and line oracle is hand-written from gate-display §3 and the GD-D9 numbers.

### Acceptance

- The five gate cases show their chip (majority, abstain, judge, writer, not run) and the GS-D2
  dash; the comparison is escaped.
- The run summary counts majority, fallback and not run; an ungated step has no line.
- The fallback judge is linked only when it was read, and never with two judge operations.
- The export holds the gate record; the reduce trace keeps its 11 fields.
- `screamingface --base <U4>` all green; `screamingface --base 4e622af75` red only on the unit 1–3
  pinned files; `repo` green.

### Deviations

- D-1 (test design, GS#10): the PRD row names an ungated step only, which passes before the
  change. The test holds a gated step (`op_synthesis_1`, `vote_gate_majority`) and an ungated step
  (`op_synthesis_2`, `vote_one_failed`) in one Case, so the row fails before the change (test-plan
  §2, RED first) and proves the `gated > 0` rule per step.
- D-2 (test design, GS#8): the escape row reads the page path only: `vote_gate_majority` (`>=`)
  and a GS-D2 copy with `cmp "<"` (`mean:conf`, a declared name, so any comparison is valid). It
  does not call `_gate_chip`.
- D-3 (kind, GS#11): CHAR, not RED. Units 1–2 already export the record (PRD "no change
  expected").

### Outcome (fill at the end — required before COMMIT)

- **Status:** Done. Commit B is built and gated. The `screamingface` and `repo` stacks are green.
  The append-only check of `screamingface --base 4e622af75` is red only on the five pinned files of
  units 1 to 3 (listed below). The same stack with `--skip-append-only` is ALL GREEN, and
  `screamingface --base 55182850c` (the unit 4 tip) is ALL GREEN with the append-only check included.
- **Start commit:** `55182850c` (unit 4 tip, `U4`). Part base `4e622af75`.
- **Actual files:** commit A: `packages/screamingface/tests/test_gate_display.py` (new), this
  ledger file. Commit B: `packages/screamingface/src/screamingface/_ui/combine_view.py` (the chip,
  the gate line, the step counters), `packages/screamingface/src/screamingface/_case_views.py`
  (rule J4 in `_reads_judge`), this ledger file. No test file, golden, schema or snapshot changed in
  commit B. No pinned edit. No file under `.claude/test-change-approvals/` was touched.
- **Commits:** A = `0db5439d1` (RED tests and this ledger section). B = the commit whose subject is
  `feat(e4b): show the gate in the Case pane, the run summary and the judge link (part 5 unit 5)`.
  C = none (spec §13).
- **Gates:**
  - Focused: `tests/test_gate_display.py`: `12 passed` (GS#1 to GS#12).
  - Neighbour regression (spec §11, 12 files): `174 passed`.
  - Lint and types on the touched files: `ruff check`, `ruff format --check` and `pyright` (0 errors)
    all pass.
  - `screamingface --base 4e622af75`: red only on the append-only check. It lists
    `tests/data/schemas/screamingface.answer.v1.json`, `tests/public_surface_snapshot.json`,
    `tests/test_evidence_words.py`, `tests/test_frozen_record_fields.py` and `tests/test_pick_output.py`.
    All five are pinned edits of units 1 to 3. With `--skip-append-only`: ALL GATES GREEN (ruff check,
    ruff format, pyright, pytest with coverage 95, notebooks, build, distribution check).
  - `screamingface --base 55182850c`: ALL GATES GREEN, the append-only check included.
  - `repo --base 4e622af75`: ALL GATES GREEN, the append-only check included.
- **RED log:** commit A, focused run `uv run pytest tests/test_gate_display.py -q -p no:randomly`:
  `10 failed, 2 passed`. The 2 passed are GS#1 (CHAR, 32 digests) and GS#11 (CHAR, export). Each of
  the 10 failed rows is an `AssertionError` in the test body.
- **Flakes:** none seen. The OME-1619 tests ran in the pytest step and passed.
- **Deviations:**
  - D-1, D-2, D-3 (planner): see the Deviations section above.
  - No new deviation in commit B. The code follows spec §3.1 and §3.2 as written.
- **Pinned edits:** none.

## Unit 6: docs (README and CHANGELOG)

### Intent

Tell the SDK user how to gate a majority vote (ans:Q1–Q4): the gate is data (one named number, one
comparison, one threshold), it reads the agreement, a declared signal of the chosen member or the
mean of a declared signal (ans:Q2), its three fallbacks (ans:Q3), what it costs and risks today
(the fallback call runs on every Case; if it fails, the Case fails; ans:Q1, C2), the missing-number
rule (P10), the verifier slot (ans:Q4), the name note (P2), and where the report shows the gate
(P16). Docs only: no code, no snapshot, no golden and no url4 change.

### Planned changes

- `packages/screamingface/README.md` — R1: the new section `### Gate the majority` between
  `### Signal sources` and `### Fusion as a named recipe`, with one code block that assigns
  `g1_agreement_abstain`, `g2_agreement_judge`, `g3_agreement_writer` and `g4_confidence_gate`.
  R2: the paragraph `**The gate.**` in `### Combine steps in the report`, before the "Numbers show
  4 significant digits" paragraph.
- `packages/screamingface/CHANGELOG.md` — B1: one part 5 bullet at position 2 of the first
  `### Features` list of `## Unreleased`, after the part 4 and part 3 bullets.
- New `packages/screamingface/tests/test_gate_docs.py` — DC#1–DC#5. It imports `_section` from
  `test_evidence_completeness_docs` and four helpers from `test_show_signals_docs`.

### Pinned edits

None.

### Test plan

- DC#1 CHAR (the five anchor headings, once each, in order). DC#2 the new section, its place, the
  names in the code, and its rules (the cost, failure, verifier, name and report sentences
  verbatim). DC#3 the README code block compiles to the four gate url4 fixtures byte for byte.
  DC#4 the `**The gate.**` paragraph, its chip and summary examples, and the export key; no new
  heading between Browse and Accounting. DC#5 one part 5 bullet at position 2, with no counted
  token.
- Regression (CHAR, no edit): `test_show_signals_docs.py`, `test_evidence_completeness_docs.py`,
  `test_signal_recipes_readme.py`, `test_combine_recipes_readme.py`, `test_pick_output.py`,
  `test_mean.py`, `test_fusion_doc_goldens.py`, `test_gate_contract_fixtures.py`.

### Acceptance

- DC#1–DC#5 green; the regression tests green.
- README diff: 0 removed lines; no added line over 100 characters. CHANGELOG diff: 2 added lines.
- `run_gates.py screamingface --base <unit 5 tip>`: all green, append-only included.
- `run_gates.py screamingface --base 4e622af75`: append-only offenders are only files of the unit
  1–3 pinned lists; with `--skip-append-only` all green. `run_gates.py repo --base 4e622af75`: green.

### Planned deviations

- DC#3 reads the four fixture files instead of importing the four builders (PRD docs §7). The
  drift guard `test_gate_contract_fixtures.py` (GA#17a, GA#17b) keeps each file byte-equal to its
  builder, so the oracle is the same; the builder names are set by the unit 3 and 4 specs.
- `test_gate_docs.py` also imports `_headings_between`, `_first_features_bullets`, `_unreleased`
  and `_COUNTED_TOKENS` from `test_show_signals_docs`, so the part 4 rules are not copied.
- README planner additions (true for units 1–5, not in the PRD delta text): A1 an undeclared
  `<name>` raises `ValueError` before any call (GA-E2); A2 a gate abstain is a scored decline, not
  a wrong answer and not a failure (epic, P13); A3 the routes of the code block are placeholders;
  A4 the code comment that each member must write a `Confidence:` line; A5 the R2 paragraph names
  the record keys and the J4 rule (the judge chip and `judge_model` name the fallback judge).
- DC#2 also checks `"agreement"`, the threshold range, the weighted-vote rule and the coverage
  phrase; DC#5 also checks the README pointer `the README section "Gate the majority"`.

### Unit 6 outcome
- **Status:** Done. The docs are written and the four gates are green. Commit A is the RED commit.
  Commit B is not needed (no code in this unit, spec §11). Commit C holds the docs.
- **Unit 5 tip (base of the unit 6 append-only check):** `76a4323d0`
  (`feat(e4b): show the gate in the Case pane, the run summary and the judge link (part 5 unit 5)`).
- **Commits:** A = `a092e0b2d` — test(e4b): RED for E4b part 5 unit 6 docs; B = none; C = the commit
  whose subject is `docs(e4b): README and CHANGELOG for the gate (part 5)`.
- **Actual files (commit C):** `packages/screamingface/README.md` (R1 section `### Gate the majority`,
  86 lines; R2 paragraph `**The gate.**`, 9 lines; 0 lines removed), `packages/screamingface/CHANGELOG.md`
  (B1 bullet at position 2 of the first `### Features`; 2 lines added, 0 removed), this ledger file.
  No code, test, golden, schema, snapshot or pinned file changed in commit C.
- **RED record (commit A):** `uv run pytest tests/test_gate_docs.py -q`: `1 passed, 4 failed`. DC#1
  passes. DC#2, DC#3, DC#4 and DC#5 fail as the spec §6 table says (the heading list, the missing
  `### Gate the majority` section, the missing `**The gate.**` text and the missing part 5 bullet).
- **Gates:**
  - Focused (spec §9 step 4): `tests/test_gate_docs.py`, `test_show_signals_docs.py`,
    `test_evidence_completeness_docs.py`, `test_signal_recipes_readme.py`,
    `test_combine_recipes_readme.py`, `test_pick_output.py`, `test_mean.py`,
    `test_fusion_doc_goldens.py`, `test_gate_contract_fixtures.py`: `97 passed`.
  - Line length: `awk 'length > 100' README.md | wc -l` gives `37` (the same count as before).
    No added line ends with a space.
  - `screamingface --base 76a4323d0` (unit 5 tip): ALL GATES GREEN, the append-only check included.
  - `screamingface --base 4e622af75`: red only on the append-only check. The offenders are
    `tests/data/schemas/screamingface.answer.v1.json`, `tests/public_surface_snapshot.json`,
    `tests/test_evidence_words.py`, `tests/test_frozen_record_fields.py` and `tests/test_pick_output.py`.
    All five are the pinned edits of units 1 to 3. This unit adds no change to them.
  - `screamingface --base 4e622af75 --skip-append-only`: ALL GATES GREEN (ruff check, ruff format,
    pyright, pytest with coverage 95, notebooks, build, distribution check).
  - `repo --base 4e622af75`: ALL GATES GREEN, the append-only check included.
- **Flakes:** none seen. The OME-1619 tests ran inside the pytest gate and passed.
- **Pinned edits:** none.
- **Deviations:**
  - Gate order. The gates ran on the final working tree before commit C, not after it (spec §11 says
    after). The tree held the same doc content that commit C records, so the result is the same.
  - DC#3 reads the four fixture files, not the four builders (PRD docs §7). This is the planned
    deviation of §10. The drift guard `test_gate_contract_fixtures.py` keeps each file equal to its builder.
  - README code block: no change to the spec text was needed. DC#3 compared all four recipes byte
    for byte with the fixtures on the first run.
  - No fix commit was needed.

## Owner decisions after the build (2026-10-16)

- P4 polarity: the keep-majority form (commit f547305cd records it in the overview, C8 and the plan).
- The owner approved the 10 pinned edits of units 1–3. Manifest:
  `.claude/test-change-approvals/OME-E4B-P5.json` (placeholder id; rename at PR-open).
- A failed fallback call fails the Case, also on the majority branch, until E4c skips the call. The
  CHANGELOG bullet now says this, as the README already did (contracts C2).
- Cleanup (owner asked): one SDK home for the gate words. `S/combine_evidence.py` holds `GateCmp`,
  `_GATE_CMPS`, `_GATE_SOURCES` and the new `_is_gate_observe`; `S/gate.py` imports them and keeps
  only its own error texts and the E4a hint. No behavior change.

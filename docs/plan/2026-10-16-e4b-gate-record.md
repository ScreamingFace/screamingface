# Plan: E4b part 5 — gate record and verifier slot

Spec: [docs/spec/2026-10-16-e4b-gate-record/](../spec/2026-10-16-e4b-gate-record/00-overview.md).
Ledger: [docs/work/2026-10-16-e4b-gate-record.md](../work/2026-10-16-e4b-gate-record.md).

## 1. Approach

- Base: branch `e4b-show-signals` (part 4, on parts 3 and 2) at `4e622af75`. Branch
  `e4b-gate-record`, worktree `.claude/worktrees/e4b-gate-record`. When part 4 changes before merge,
  rebase onto its new tip.
- One branch, one commit group per unit, in the order of §2. The units share `S/reducer.py`,
  `E/combine/endpoint.py`, the v1 schema snapshots and the public surface snapshot, so the order is
  linear.
- Each unit: a full unit spec (files, signatures, data shapes, exemplar, edge cases, what not to do,
  verification), then RED, then GREEN, then a design review against the PRD as the rubric, then one
  fix round. A structural finding means a re-spec, not a second fix round.
- TDD inside each unit follows the PRD §7 order: CHAR rows first, then RED → GREEN → REFACTOR. A PIN
  row is the owner-approved edit of a pinned file.
- One ledger for the part (`docs/work/2026-10-16-e4b-gate-record.md`), one section per unit.
- No live provider call, no paid test, no eval run. Engine runs use the Engine-world fake gateway.

## 2. Units

| # | Unit | PRD rows | Main files | Stacks | Pinned files |
|---|---|---|---|---|---|
| 0 | docs (spec) | — | this plan, the spec, the ledger | repo | none |
| 1 | gate-record | GR#1–14, VS#1–3 | `E/combine/ports.py` (words, `GateCmp`, `GateOtherwise`, `GateBranch`, `GATE_OBSERVE`), `E/combine/spec.py` (`GateSpec`, `CombineSpec.gate`, `_check_gate`), `E/combine/evidence.py` (`GateRecord`, `CombineEvidence.gate`, `.verifier`, invariants); `S/answer.py`, `S/combine_evidence.py` (`CombineGate`, `CombineEvidence.gate`), `S/report.py` (export), `S/_evaluation/combine_evidence.py` (`gate`, `verifier`), `S/_evaluation/combine_spec.py` (`_OPTIONAL_SPEC_KEYS`); new `ET/test_combine_gate_words.py`, `ST/test_gate_words.py` | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`, `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`, `ST/data/schemas/screamingface.answer.v1.json`, `ST/public_surface_snapshot.json`, `ST/test_pick_output.py` (:250-264), `ST/test_evidence_words.py` (:372, :460-475), `ET/test_combine_pick_output.py` (:341-352), `ET/test_combine_evidence_words.py` (:310-322) |
| 2 | gate-decision | GD#1–20 | `E/combine/spec.py` (`_SIGNAL`), `E/combine/ports.py` (`parse_label` moved here, `judge_reply(key=)`), `E/combine/operators/judge.py` (import `parse_label`), new `E/combine/gate.py`, `E/combine/endpoint.py` (`_combine`, `_decide`, `_gated`, `_not_run`, `_abstain`, `_evidence`); new `ET/test_combine_gate.py` | screamingface-engine, screamingface, repo | `ET/data/combine_contract/evidence_cases.json`, `ET/test_combine_evidence_contract_fixture.py` (append builders and `SCENARIOS` lines), `ST/test_combine_evidence_contract.py` (append one `_EXPECTED_NAMES` line after :54), `ST/test_frozen_record_fields.py` (:184, 32 → 37) |
| 3 | gate-api | GA#1–20, VS#4–6 | new `S/gate.py`, `S/reducer.py` (`_ReducerPlan.gate`, `Vote` `gate`, `verify`, `_vote_plan`, `_render`, `_rebuild`, `_from_spec_parts`), `S/fusion.py` (gate name check), `S/_evaluation/combine_spec.py` (write `gate`), `S/_evaluation/topology.py` (`_signal_role`, `_decode_signal`, `_operation_shape`), `S/_evaluation/reducer_signals.py` (`_signal_call_role`), `S/url4.py` (`_model_signal`, `_rebuilt_reducer`), `S/__init__.py`; new `ST/test_gate_api.py`, `ST/test_gate_contract_fixtures.py`, four new `ET/data/combine_contract/gate_*_vote_candidate.url4`, new `ET/test_combine_gate_run.py` | screamingface-engine, screamingface, repo | `ST/public_surface_snapshot.json` |
| 4 | gate-display | GS#1–12 | `S/_ui/combine_view.py` (`_gate_chip`, `_gate_verdict`, `_StepSummary` counters, `_gate_line`), `S/_case_views.py` (`_reads_judge` J4); new `ST/test_gate_display.py` | screamingface, repo | none |
| 5 | docs | DC#1–5 | `packages/screamingface/README.md` (`### Gate the majority`, the `**The gate.**` paragraph), `packages/screamingface/CHANGELOG.md`; new `ST/test_gate_docs.py` | screamingface, repo | none |

77 TDD rows in total (GR 14, VS 6, GD 20, GA 20, GS 12, DC 5).

## 3. Order and dependencies

```mermaid
flowchart LR
    U0[0 spec] --> U1[1 gate-record] --> U2[2 gate-decision] --> U3[3 gate-api] --> U4[4 gate-display] --> U5[5 docs]
```

- Unit 1 comes first: every other unit uses its words and records. It holds most pinned edits, so
  one owner approval covers most of them.
- Unit 2 before unit 3: the Engine must accept the `fallback_*` context keys and decide, before the
  SDK fixtures of unit 3 can run in the Engine world (GA#18) and before the signal-key bind (GA#16)
  can pass.
- Unit 3 before unit 4: the display tests use the contract cases of unit 2 and, for J4, the
  operation shape of unit 3 (`op_judge_1`, kind `judge`).
- Unit 5 is last: its code block compiles to the unit 3 fixtures.

## 4. Gates per unit

Run one stack at a time, from the worktree root. Never run two gate stacks at the same time.

- Engine venv: `cd apps/screamingface-engine && uv sync --dev` (no `inspect` extra).
- SDK venv: `cd packages/screamingface && uv sync --extra notebook`.
- `uv run .claude/scripts/run_gates.py screamingface-engine --base 4e622af75` (units 1, 2, 3)
- `uv run .claude/scripts/run_gates.py screamingface --base 4e622af75` (every unit)
- `uv run .claude/scripts/run_gates.py repo --base 4e622af75` (every unit)
- Append-only: units 1–3 edit pinned files. If the append-only check is the only red result, list
  every offending file, then rerun that stack with `--skip-append-only` to prove the rest is green.
  The build never writes or edits `.claude/test-change-approvals/`; the owner approves after the
  build (§6).
- A suite with no progress for 15 minutes is stopped and run once more.
- Known flaky tests (OME-1619): `test_combine_inspect_rules.py::test_inspect_rules_stay_linear_on_hostile_input`,
  the `test_ws.py` nack tests, `test_evaluation_outcome.py::test_a_callback_exception_aborts_the_evaluation_and_is_re_raised`.
  Rerun a failing one alone; if it passes alone, record it as a flake.

## 5. Exit criteria

| Criterion | Closed by |
|---|---|
| A gate keeps the majority when `observed cmp threshold` holds, else takes the fallback | GD#2–5, GD#8 |
| The gate reads agreement, the chosen member's declared signal, or the mean over the members (ans:Q2) | GD#2, GD#6, GD#7 |
| Abstain, judge and writer fallbacks work, and the abstain has its own reason (ans:Q3) | GD#3–5, GR#2 |
| The fallback call runs on every Case, and the evidence records the comparison and the branch (ans:Q1) | GA#18, GR#6, GD#2 |
| The majority branch never reads the fallback reply (E4c adds the skip with no wire change) | GD#9, GD#10 |
| `verify=` accepts only None, and the evidence reserves `verifier` (ans:Q4) | VS#1–6 |
| An undeclared gate name fails before any call | GA#8 |
| A gated recipe rebuilds from its url4; a hand edit does not | GA#12, GA#13 |
| The Case pane, the run summary and the export show the gate | GS#2–7, GS#9, GS#11 |
| No byte change for an ungated vote, spec, evidence, url4 or report | GR#1, GD#1, GA#1, GS#1 |
| Only the listed pinned files change | the append-only gate, §6 |
| Each user decision with a testable effect is pinned by a test | test-plan §2 |

## 6. User actions

1. Approve the spec and this plan, including the proposed items P1–P21 and the scope notes N1–N5.
   These items need an explicit decision:
   - P1, P2: the gate lives on `sf.Vote` only, and the public name is `sf.Gate` (the corrective-loop
     route `/gate` is a different, internal concept).
   - P4: `>=` keeps the majority at equality; an agreement gate takes only `>=` or `>`.
   - P6: the judge fallback is `returns="label"` only (a scores judge is deferred, D2).
   - P10: a missing number takes the fallback; a vote with no answer does not run the gate.
   - P13: the new abstain reason is named `gate_not_met`.
   - P15: no combine-spec key for `verify` in this part; the evidence reserves `verifier` as null.
   - P16: the report-trace.v1 field set does not change; the export shows the record in
     `operations[].combine.gate`.
2. Approve the edits to pinned files after the build (exact list; each is the smallest edit):
   - unit 1:
     - `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json` (regenerated: optional `gate`);
     - `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` (regenerated: optional `gate`, `verifier`; `gate_not_met` in the two reason enums);
     - `packages/screamingface/tests/data/schemas/screamingface.answer.v1.json` (regenerated: `gate_not_met`);
     - `packages/screamingface/tests/public_surface_snapshot.json` (regenerated: `CombineGate`, `CombineEvidence.gate`);
     - `packages/screamingface/tests/test_pick_output.py` (lines 250-264: `gate_not_met` in the two sorted lists);
     - `packages/screamingface/tests/test_evidence_words.py` (line 372: 12 → 13; lines 460-475: `gate_not_met` in the two sorted lists);
     - `apps/screamingface-engine/tests/unit/test_combine_pick_output.py` (lines 341-352: the four-word tuple, the last `AnswerReason`, the last word of each `no_votes` list);
     - `apps/screamingface-engine/tests/unit/test_combine_evidence_words.py` (lines 310-322: `gate_not_met` after `output_missing`).
   - unit 2:
     - `apps/screamingface-engine/tests/unit/data/combine_contract/evidence_cases.json` (regenerated: five new cases; the 32 existing cases keep their bytes);
     - `apps/screamingface-engine/tests/unit/test_combine_evidence_contract_fixture.py` (appended: five builders and five `SCENARIOS[...]` lines);
     - `packages/screamingface/tests/test_combine_evidence_contract.py` (one appended `_EXPECTED_NAMES |= {...}` line);
     - `packages/screamingface/tests/test_frozen_record_fields.py` (line 184: 32 → 37).
   - unit 3:
     - `packages/screamingface/tests/public_surface_snapshot.json` (regenerated again: `Gate`, `Vote.__init__` with `gate` and `verify`, the `Vote` fields).
   - units 4–5: no pinned file. If the append-only gate names another file, the build stops that
     unit and records it in the ledger.
3. At PR-open: file the leaf under the E4b epic OME-1290, and the approval manifest for the pinned
   edits above.

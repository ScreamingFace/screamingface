# Plan: E4c — choose whether a model runs

Spec: [docs/spec/2026-10-22-e4c-routers-cascades/](../spec/2026-10-22-e4c-routers-cascades/00-overview.md).
Ledger: [docs/work/2026-10-22-e4c-routers-cascades.md](../work/2026-10-22-e4c-routers-cascades.md).

## 1. Approach

- Base: ref `e4b-integrated` (`031780873`). Branch `e4c-routers-cascades`, worktree
  `.claude/worktrees/e4c-routers-cascades`. When E4b lands on main, rebase E4c with
  `git rebase --onto origin/main e4b-integrated`.
- Three PRs (ans:Q11), stacked: PR-1 → PR-2 → PR-3 (overview §9). Units in each PR are linear
  because they share `E/world/branch.py`, the SDK compiler and the snapshots.
- Each unit: a full unit spec (files, signatures, data shapes, exemplar, edge cases, verification),
  then RED, then GREEN, then a design review against the PRD as the rubric, then one fix round. A
  structural finding means a re-spec, not a second fix round.
- TDD follows each PRD §7: CHAR rows first, then RED → GREEN → REFACTOR. A PIN row waits for the
  owner's approval of the pinned edit; the build reports the list, it never writes
  `.claude/test-change-approvals/`.
- Input gates need a selector to read, so the selectors are built in PR-1 (unit 4), before the
  Engine-world runs of the core (unit 5). The Engine-world core runs read `sf.Keywords` labels
  (pure, no model call). `sf.budget.remaining()` arrives in PR-3.
- The `fail_closed` code joins both vocabularies in PR-1 (unit 1), because the Gate word
  `"fail_closed"` exists from PR-1 and the helper's import-time check refuses an undeclared code
  [existing `E/benchmarks/failure_classes.py:86-95`].
- Offline only: no live provider, no paid test, no eval run (test-plan §1).
- Gates per unit: `timeout 1500 uv run --script .claude/scripts/run_gates.py <stack> --base
  e4b-integrated`, one stack at a time.

## 2. Units

Row numbers are the TDD row numbers of each PRD §7 (`BC#3` = branch-core row 3). Every row is in
exactly one unit.

| # | PR | Unit | TDD rows | Main files | Stacks |
|---|---|---|---|---|---|
| 0 | — | docs (spec, plan, ledger) | — | this plan, the spec, the ledger | repo |
| 1 | PR-1 | vocabulary + attribution | BC#1, #2 (CHAR first), #7, #8, #26, #29, #30; GU#3, #4, #5, #6, #7, #29 | `E/benchmarks/contract.py` (`OperationOutput.decision`, `fail_closed`), `E/error_text.py`, `E/benchmarks/failure_classes.py` (`fail_closed` helper), `S/_report_primitives.py`, `E/operation_calls.py` (`record_gate_call`, `OperationCall.decision`, `.pending`, `.gate_record`), `E/benchmarks/operation_outputs.py` (walk limited to `gate_N_block`, pattern, `final_operation_abstained`), `S/_operation_bindings.py` (incl. `TOPOLOGY_BINDING`), `S/url4.py:74-76`, the Engine-only `ET/data/combine_contract/binding_names.json`, new `GateDecision` model | screamingface-engine, screamingface |
| 2 | PR-1 | Engine branch endpoints | BC#3, #4, #5, #6, #9, #20, #24, #31, #32, #37, #39 | new `E/world/branch.py` (DECIDE with `gate=` param, OPEN, JOIN copying the panel result, AFTER), routes beside `E/benchmarks/ensemble/policy.py` | screamingface-engine |
| 3 | PR-1 | SDK renderer + internal `BranchNode` | BC#17a, #25, #28, #34, #35 | new `S/_evaluation/branch.py` (exemplar `S/_evaluation/corrective.py`; Gate block `gate_N_block`, AFTER source, D5 check), `S/recipe.py` (`_recipe_kind` `gate`), `S/_evaluation/topology.py` (kind `gate`) | screamingface |
| 4 | PR-1 | selectors | SL#1–#25; BC#17, #33 | new `S/_surface/selectors.py`, `E/world/branch.py` (KEYWORDS with `summary`, literal-name rule), `E/combine/ports.py` (`parse_selector_reply`), `S/accounting.py`, `label-template@1` | both |
| 5 | PR-1 | Engine-world core runs | BC#12, #13, #14, #15, #16, #18, #19, #21, #22, #23, #27, #36, #38, #40 | renderer + endpoints end to end on internal Gates that read Keywords (fake gateway) | both |
| 6 | PR-1 | public `sf.Gate` (incl. panel gates) | GT#1–#3 (CHAR first), GT#4–#32; BC#6b, #10 | `S/_surface/gate.py`, `S/gate.py`, `S/_surface/lowering.py`, `S/_surface/rebuild.py`, `S/url4.py` (`_PROVED_SPEC_KEYS`), `E/combine/spec.py` (gate on any reducer), CorrectiveLoop refusal (GT-27) | screamingface, screamingface-engine |
| 7 | PR-1 | lazy E4b fallback | LF#1–#3 (CHAR first), LF#4–#24; BC#11 | `E/combine/endpoint.py` (`phase=decide`, pending outcome with `gate_record`), `S/reducer.py`, `S/gate.py`, `S/_evaluation/reducer_signals.py`, gate url4 fixtures | both |
| 8 | PR-1 | `sf.Cascade` | CA#1 (CHAR first), CA#2–#26, #11a; BC#6a | new `S/_surface/cascade.py` (exemplar `S/_surface/fusion.py`; stage panels url4 `quorum=0`), `sf.answered()` in `S/_surface/refs.py`, `CascadeSeedWarning` | screamingface, screamingface-engine |
| 9 | PR-1 | report: decode, Gate sections, summary | RP#1, #2 (CHAR first), RP#3–#14, #16, #17, #18, #20, #22, #23, #25, #26, #29–#35 | `S/case_result.py`, `S/_evaluation/gate_decision.py`, new `S/_ui/branch_view.py`, `S/_ui/report_view.py`, `S/report.py` | screamingface |
| 10 | PR-2 | guards | GU#1, #2 (CHAR first), GU#8–#13, #15–#28 | guard patterns on Gate + selectors; jailbreak fixture | both |
| 11 | PR-2 | skip members | SM#1, #2 (CHAR first), SM#2a, #2b, SM#3–#17, #5a, #5b, #19–#25 | `S/_surface/fanout.py`, `S/_evaluation/candidate.py` (required slots under `"all"`, optional + `quorum=0` under a numeric quorum, DECIDE before the panel), `E/combine/endpoint.py` (`selection` exclusion, numeric floor over selected), `E/combine/evidence.py` (`skipped`, NR-I4) | both |
| 12 | PR-2 | report: skip lines | RP#24 | `S/_ui/branch_view.py`, `S/_ui/combine_view.py` | screamingface |
| 13 | PR-3 | budget | BU#1–#28; SM#18; GU#14 | new `S/_surface/budget.py` (`Budget`, `Estimate`, `budget.remaining`), `E/budget.py` (`BudgetStage`), `E/benchmarks/invocation.py` (bind cap per Attempt in a ContextVar set before the expression runs), `E/world/branch.py` (fold in DECIDE), `S/report_trace.py` producer, reproduction compare | both |
| 14 | PR-3 | report: budget lines | RP#11a, #15, #19, #21, #27, #28 | `S/_ui/branch_view.py` | screamingface |
| 15 | PR-3 | docs | DC#1 (CHAR first), DC#2–#21 | `packages/screamingface/README.md`, `CHANGELOG.md`, `examples/20_routers_cascades.ipynb`, `scripts/build_notebooks.py`, docstrings | screamingface, repo |

Ordering notes (review 3 F11): BC#17 (body references a hoisted selector) needs selectors, so it
is in unit 4; BC#9 no longer holds a budget case (it moved to budget #5, unit 13); RP#11 renders
no `budget.remaining` condition (RP#11a, unit 14, does). BC#6a needs `sf.Cascade` (unit 8) and
BC#6b a public input Gate with a recipe body (unit 6). BC#10 (DECIDE after delayed ancestors) needs a panel gate, so it is in unit 6;
BC#11 (an E4b abstain still marks the Case) needs the lazy shape, so it is in unit 7. Unit 5 runs
internal Gates over Keywords labels only; no PR-1 row needs the budget (BC-24 checks the recorder,
the spend assertion is budget BU-22).

294 TDD rows in total (test-plan §4). Pinned edits per PR: test-plan §5.

## 3. Stop points for the owner

- After unit 0: spec + plan approval (P1–P26 in overview §6).
- End of each PR: the pinned-edit list for the manifest.
- Before any push or PR: the owner's word; Linear leaves under OME-1291 at PR-open.

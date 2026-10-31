# Plan: E4b part 1 — combine extensions

Spec: [docs/spec/2026-10-13-e4b-combine-extensions/](../spec/2026-10-13-e4b-combine-extensions/00-overview.md).
Ledger: [docs/work/2026-10-13-e4b-combine-extensions.md](../work/2026-10-13-e4b-combine-extensions.md).

## 1. Approach

- Base: local branch `e4a-integrated` (`e5523a20d`), the whole E4a stack on origin/main `3cf66b545`.
  E4a is under review, so its commits will change. After each E4a change, move the bottom E4b
  branch with `git rebase --update-refs --onto <new OME-1593 tip> e4a-integrated <top branch>`,
  then move the marker.
- One linear stack of 7 code units on top of the docs branch `e4b-combine-extensions`. The units
  share `README.md`, `CHANGELOG.md`, `FLOW_OPERATOR_IDS` and the v1 schema snapshots, so a linear
  stack avoids merge conflicts in those files.
- Each unit: a full unit spec (files, signatures, data shapes, exemplar, edge cases), then
  implementation, then a design review against the PRD as the rubric, then one fix round. A
  structural finding means a re-spec, not a second fix round.
- TDD inside each unit follows the PRD §7 order: CHAR rows first, then RED → GREEN → REFACTOR.
- The catalog-and-schema rows (CS) fold into the unit that adds each name.

## 2. Units

| # | Unit (branch) | PRD rows | Main files |
|---|---|---|---|
| 0 | docs (`e4b-combine-extensions`) | — | this plan, the spec, the ledger |
| 1 | selection input (`e4b-selection-input`) | SI#1–13, CS#8, CS#10 | `E/combine/ports.py` (`CombineInput.input`), `E/combine/endpoint.py`, `E/combine/operators/selection.py`; README :276-277, :592-595, :621, :657-659; CHANGELOG :53, :57 |
| 2 | recipes (`e4b-recipes`) | RC#1–13 | SDK fixture generator, `ET/data/combine_contract/recipe_*.url4`, engine run tests, README "Combine recipes" |
| 3 | mean (`e4b-mean`) | MN#1–25, CS#1–3, CS#5–7, CS#9, CS#11 | `E/combine/operators/reduce.py`, `select.py` (`participants`), `spec.py`, `ports.py`, `evidence.py`, `endpoint.py`; `S/reducer.py` (`Mean`), `S/blocks.py`, `S/combine_evidence.py`, `S/__init__.py`; spec and evidence snapshots |
| 4 | weighted median (`e4b-weighted-median`) | WM#1–15, CS#1–2 | `reduce.py`, `spec.py` (`median` weights optional); `S/reducer.py` (`Median`), `S/blocks.py` |
| 5 | judge order (`e4b-judge-order`) | JO#1–13 | `S/judge.py`, `S/blocks.py`, `S/selection.py`, `S/reducer.py` (shared judge check) |
| 6 | filter by judge (`e4b-filter-judge`) | FJ#1–12 | `S/selection.py` (`Filter`), `S/reducer.py` (pairing rule), `S/blocks.py` |
| 7 | pick output (`e4b-pick-output`) | PO#1–17, CS#4 | `E/combine/operators/fields.py`, `signals.py`, `ports.py` (`output_missing`); `S/fields.py`, `S/answer.py`, `S/blocks.py`; evidence and answer snapshots |

Each of units 3–7 adds its own README recipe row and CHANGELOG entry. 119 TDD rows in total.

## 3. Order and dependencies

```mermaid
flowchart LR
    U0[0 docs] --> U1[1 selection input] --> U2[2 recipes] --> U3[3 mean] --> U4[4 weighted median] --> U5[5 judge order] --> U6[6 filter by judge] --> U7[7 pick output]
```

- Unit 1 comes before unit 2, because the S7, S9 and S10 recipe tests assert the new envelope.
- Unit 4 reuses the weight check and `participants` from unit 3.
- Unit 6 reuses the shared judge check (JO-D1) from unit 5.

## 4. Gates per branch

- Engine: a `uv sync --dev` venv (do not install the `inspect` extra), then
  `uv run .claude/scripts/run_gates.py screamingface-engine --base <parent>`.
- SDK: `uv sync --extra notebook` (as CI does), then
  `uv run .claude/scripts/run_gates.py screamingface --base <parent>`.
- Repo: `uv run .claude/scripts/run_gates.py repo --base <parent>`.
- Append-only: the edited pinned tests are listed in an owner approval manifest (§6). No
  `--skip-append-only` without it.
- The tip: every stack green, and a clean rebase onto `e4a-integrated`.

## 5. Exit criteria

| Criterion | Closed by |
|---|---|
| Every scenario S1–S11 has a recipe that runs offline end to end | RC#1–11, MN#22–23, JO#12, PO#17 |
| The writer after Rank or Filter sees the Case input | SI#3–9 |
| The mean is exact in its sums, rounded once to 34 digits, and drops unusable weights | MN#1–4 |
| A weight-dropped member never wins `nearest` | MN#3, WM#5 |
| Judge `order="min"` tells the judge "lower is better" | JO#4 |
| Engine and SDK vocabularies stay equal | CS#1–11 |
| No compiled-url4 byte change for existing recipes | WM#1, JO#2, PO#1, SI#2 |
| Each user decision with a testable effect is pinned by a test | test-plan §2 |

## 6. User actions

1. Approve the spec and this plan (plain words), including the proposed items P1–P10 and the scope
   notes N1–N3 in the overview.
2. Approve the edits to pinned tests when each unit asks for them:
   - unit 1: the writer test in `ET/test_combine_rank_world.py`, the filter run at
     `ET/test_sdk_candidate_contracts.py:155`, and `ET/test_combine_selection.py:26,74`;
   - unit 3: the `combine-spec.v1` and `combine-evidence.v1` snapshots, `ST/test_frozen_record_fields.py`,
     `ST/public_surface_snapshot.json`;
   - unit 4: the Median `TypeError` pin at `ST/test_signal_weighted_vote.py:32-35`, the public surface;
   - unit 5: the public surface;
   - unit 6: the Filter `score:judge` message pin at `ST/test_filter.py:343`, the public surface;
   - unit 7: the `best_holder@1` args schema pin at `ET/test_rest_operators.py:89-93`, the
     `by_field@1` and `best_holder@1` golden files, the `answer.v1` and `combine-evidence.v1`
     snapshots, the public surface.
3. At PR-open: confirm the E4b epic in Linear. The leaves are filed under it then.

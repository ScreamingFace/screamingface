# PRD: Catalog, vocabulary and v1 schema sync (component)

**Source:** ans:Q1, ans:Q5, ans:Q9, ans:Q12 · **Priority:** P0 (every other PRD depends on it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §4, §7, §8, §10](../erd.md)

## 1. Summary and flows served

This component keeps the engine and the SDK in agreement when E4b adds an operator, a reducer name,
an abstain reason, or an evidence field. It serves all flow PRDs: [mean](mean.md),
[weighted-median](weighted-median.md), [judge-order](judge-order.md),
[filter-judge](filter-judge.md), [pick-output](pick-output.md),
[selection-input](selection-input.md) and [recipes](recipes.md).

A flow PRD names the new id or field. This PRD owns the rules that make the change safe.

## 2. Background and constraints

- "additive edit, no need to care abour versions for now" [stated ans:Q5]. The v1 schema ids do not
  change. E4a is unreleased.
- A behavior change of an operator is normally a new `@version` [existing E/combine/ports.py:25-27].
  Under ans:Q5, an optional new arg that keeps the old behavior when absent, and the new `input`
  key in the selection envelope, are edits of the same id. [stated ans:Q5]

### 2.1 Current behavior

- The SDK pins the engine catalog with `FLOW_OPERATOR_IDS`. A test checks that it equals the
  engine builtins. [existing ST/_combine_flow_fixtures.py:19] [existing ET/test_sdk_flow_catalog_fixture.py:37]
- Each builtin operator has exactly one golden fixture.
  [existing ET/test_combine_operators_golden.py:49-68]
- The SDK checks the engine catalog (`GET /v1/operators`) before a run, and refuses a missing id.
  [existing S/_evaluation/operators.py:29-78]
- The frozen-schema test never overwrites an existing snapshot, even with
  `UPDATE_SCHEMA_SNAPSHOT=1`. Update mode writes only a missing file, and the run still fails once.
  [existing ET/test_wire_schema_freeze.py:29-71]
- The abstain reasons are a closed set in three engine places (`AbstainReason` and
  `ABSTAIN_REASONS`; `NoVotes` refuses any other reason) and in the SDK.
  [existing E/combine/ports.py:51,61,64,104-112] [existing S/answer.py:22,32]
- The failure codes are a closed set, pinned on both sides.
  [existing ET/test_failure_classes.py:88-91] [existing ST/unit/test_failure_code_conformance.py:70-86]
- The SDK `CombineEvidence` refuses a reducer name that is not in `REDUCER_NAMES`.
  [existing S/combine_evidence.py:258]
- The record field lists are pinned. [existing ST/test_frozen_record_fields.py]

**Delta.** Add `mean@1`, `weighted_mean@1` and `weighted_median@1` to both catalogs. Add the
reducer name `mean`, the abstain reason `output_missing`, and the evidence field `mean`. Regenerate
the three v1 snapshots by deleting each file and running the freeze test in update mode. Add **no**
new failure code.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **CS-1** Given the E4b engine, when a client calls `GET /v1/operators`, then the list contains
  `mean@1`, `weighted_mean@1` and `weighted_median@1`, each with stage `reduce`. [stated ans:Q1]
  [stated ans:Q9]
- **CS-2** Given the SDK list `FLOW_OPERATOR_IDS` with the three new ids in sorted order, when the
  catalog pin test runs, then it passes. [implied]
- **CS-3** Given the regenerated `combine-spec.v1` snapshot, when the freeze test runs, then the
  reducer enum contains `mean` and the test passes under the same schema id. [stated ans:Q5]
- **CS-4** Given the regenerated `combine-evidence.v1` and `answer.v1` snapshots, then both list the
  abstain reason `output_missing`, and the evidence schema has the optional field `mean`.
  [stated ans:Q5] [stated ans:Q12]

### 3.2 Error paths

- **CS-E1** Given an SDK with `sf.Mean` and an engine without `mean@1` in its catalog, when the user
  runs the candidate, then the SDK refuses before any model call and names the missing operator
  ids. [existing S/_evaluation/operators.py:47-67]
- **CS-E2** Given an evidence record with reducer `mean` and an SDK without `mean` in
  `REDUCER_NAMES`, then the SDK record refuses it. This is the drift guard. [existing S/combine_evidence.py:258]

### 3.3 Derived scenarios (risk-ordered)

- **CS-D1** (H×M) [proposed — gap §per-connection/dependency] Given a new operator in the engine but
  no golden fixture, then the golden test fails, naming the missing fixture.
  [existing ET/test_combine_operators_golden.py:60-68]
- **CS-D2** (H×L) [implied] Given the `DECLARED_FAILURE_CODES` set, then E4b adds no code: every new
  refusal is `combine_spec_invalid`, and every new empty result is an abstain. This keeps the pins
  in `test_failure_classes.py` unchanged.
- **CS-D3** (M×M) [proposed] Given a `CHANGELOG.md` entry for each new SDK name, then each entry
  says which operator ids the engine catalog must have, in the same form as the E4a entries.
  [existing packages/screamingface/CHANGELOG.md:37-53]
- **CS-D4** (M×L) [implied] Given `report.v1` and `report-trace.v1`, then neither snapshot changes,
  because neither lists reducer names or abstain reasons.

## 4. Non-functional requirements

- **Approvals.** Each pinned test that E4b edits (not appends to) is listed in an owner approval
  manifest `.claude/test-change-approvals/<ticket>.json`. The append-only gate refuses the branch
  without it. [existing .claude/scripts/run_gates.py:382-498]
- **Observability.** A refused catalog check names the missing ids in the error text.
  [existing S/_evaluation/operators.py:47-67]

## 5. Out of scope

- A new schema id (`v2`) for any record. [stated ans:Q5]
- Any change to `report.v1`. [implied]

## 6. Open questions

None.

## 7. TDD plan

Order: core-out. Each row lands in the unit that adds the name (plan §2).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `operator_catalog_lists_the_new_reduce_ids` | unit | CS-1 | H×M | register the descriptors in `builtins.py` |
| 2 | `test_sdk_flow_catalog_names_exactly_the_builtins` passes with the new ids on both sides | unit | CS-2 | H×M | add ids to `FLOW_OPERATOR_IDS` in sorted order; update the id count in its comment (:17) |
| 3 | `combine_spec_v1_lists_mean_in_the_reducer_enum` | unit | CS-3 | H×M | add `mean` to the `Reducer` Literal; delete the snapshot, run the freeze test with `UPDATE_SCHEMA_SNAPSHOT=1`, rerun |
| 4 | `answer_and_evidence_v1_list_output_missing` | unit | CS-4 | H×M | extend `AbstainReason` and `ABSTAIN_REASONS` (engine) and the SDK set; regenerate both snapshots the same way |
| 5 | `combine_evidence_v1_has_an_optional_mean_field` | unit | CS-4 | M×M | add `mean: str \| None = None` to the engine and SDK records |
| 6 | `sdk_refuses_an_engine_without_the_mean_operators` | unit | CS-E1 | H×M | no change; pins the check for the new ids |
| 7 | `sdk_combine_evidence_accepts_reducer_mean` | unit | CS-E2 | M×M | `REDUCER_NAMES` derives from the Literal |
| 8 | `declared_failure_codes_are_unchanged_by_e4b` (CHAR) | unit | CS-D2 | H×L | no code |
| 9 | `changelog_entries_name_the_required_operator_ids` | unit | CS-D3 | M×L | doc check in the SDK tests |
| 10 | `report_v1_and_trace_v1_snapshots_are_unchanged` (CHAR) | unit | CS-D4 | M×L | passes today and after |
| 11 | `frozen_record_fields_include_evidence_mean` | unit | CS-4 | M×M | approved edit of the pinned field list |

CS-D1 is covered by the existing golden test; each new id adds its golden in its own PRD.

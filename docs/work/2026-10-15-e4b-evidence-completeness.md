---
ticket: unfiled   # epic OME-1290 is the parent; the leaf is filed at PR-open
stack: screamingface-engine, screamingface, repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-15
finished:
---

# e4b-evidence-completeness — E4b part 2, evidence completeness

Spec: `docs/spec/2026-10-15-e4b-evidence-completeness/`. Plan:
`docs/plan/2026-10-15-e4b-evidence-completeness.md`. Branch `e4b-evidence-completeness`, base
`0f4b9e292`. One section for each unit, in the order of plan §2.

## Unit 1 — words and schema (ES#1–4, ES#6–9, ES#11, ES#13, ES#14)

### Intent

This unit adds the part 2 words and wire keys on both sides. The record status `"excluded"`, the
reasons `no_signal` and `no_weight`, the optional member key `rank` and the optional evidence key
`cut` become valid, checked and readable. No engine code writes them yet (units 2 and 3). Every
evidence without a new value keeps its v1 bytes (P11). Decisions: Q3, Q4, P2, P3, P11, P12, P14.

### Planned changes

- Engine: `E/combine/ports.py` (`RecordStatus`, `ExcludeReason`, `EXCLUDE_REASONS`, `Cut`),
  `E/combine/evidence.py` (`AnswerRecord.status`, `.reason`, `.rank`, rules AR-I3 and AR-I4;
  `CutRecord`; `CombineEvidence.cut`).
- SDK: `S/answer.py` (words, `EXCLUDE_REASONS`, the docstring mapping, the `sf.Answer` rule for
  `"excluded"`), `S/combine_evidence.py` (`CombineAnswerRow.rank`, `CombineCut`,
  `CombineEvidence.cut`, `_rank`, `_ranks`), `S/_evaluation/combine_evidence.py` (optional keys
  `rank` and `cut`), `S/report.py` (export `CombineCut`).
- Tests (new): `ET/test_combine_evidence_words.py`, `ST/test_evidence_words.py`.
- Stub in commit A only: `CombineCut` in `S/combine_evidence.py` (raises `NotImplementedError`).

### Pinned edits (owner approval)

- P-1 `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` (regenerated).
- P-2 `packages/screamingface/tests/data/schemas/screamingface.answer.v1.json` (regenerated).
- P-3 `packages/screamingface/tests/public_surface_snapshot.json` (regenerated).
- P-4 `packages/screamingface/tests/test_pick_output.py` (two lines added to the expected reason
  list of `test_answer_v1_lists_output_missing`). Not in plan §6: see Deviations D-1.

### Test plan

- 11 PRD rows: ES#1 (CHAR, both sides), ES#2, ES#3, ES#4, ES#6, ES#7, ES#9 (RED, both sides),
  ES#8, ES#11, ES#13 (RED, SDK), ES#14 (RED, both sides).
- CHAR first: ES#1 passes on the parent (28 engine fixture cases, both sides).
- RED: each refusal test starts with a positive control, so it fails on the missing behavior. The
  one stub is `CombineCut` (raises `NotImplementedError`).
- Oracles are hand-computed: the ranks of scores 0.3, 0.9, 0.6, 0.1 (order max) are 3, 1, 2, 4;
  `dropped` with one failed and one excluded member is 1.

### Acceptance

- An `AnswerRecord` with `status="excluded"`, `reason="no_weight"`, a value and `weight=null` is
  valid (ES-2). A wrong reason or a wrong rank is refused on both sides.
- The SDK decodes an evidence with an excluded row, `rank` and `cut`, and the trace extract entry
  shows `"excluded"`.
- The v1 schema ids do not change. Only the listed words and keys are added to P-1, P-2, P-3.
- No url4 file, no combine spec and no `evidence_cases.json` change.
- Engine, SDK and repo gates green, except the append-only check, which lists exactly P-1 to P-4.

### Deviations

- D-1: `test_pick_output.py::test_answer_v1_lists_output_missing` pins the exact `reason` list of
  `answer.v1.json`. P12 adds two words to that list, so this test must change. It is an extra
  pinned edit (P-4) that plan §6 did not list. The edit adds two lines and changes no other line.
- D-2: The `sf.Answer` excluded checks are in a helper, `_check_excluded`, called from
  `_check_status`. The spec puts them in `_check_status`. Ruff C901 (9 > 8) and PLR0912 (8 > 7)
  failed on the inline form. The helper has the same checks and messages.
- D-3: `ruff check --fix` sorted the import block of `combine/evidence.py`. The module docstring
  was wrapped by hand in the GREEN commit. Neither change alters behavior. Review round 1 (below)
  re-wrapped that docstring again.

### Outcome (fill at the end — required before COMMIT)

- **Status:** done. Commit A is the RED commit. Commit B is the GREEN commit (the commit after
  this ledger text). Unit 1 is complete. The part is not complete.
- **Actual files:** commit A (RED): the ledger, `apps/screamingface-engine/tests/unit/test_combine_evidence_words.py`, `packages/screamingface/tests/test_evidence_words.py`, the `CombineCut` stub in `packages/screamingface/src/screamingface/combine_evidence.py`. Commit B (GREEN): `apps/screamingface-engine/src/screamingface_engine/combine/ports.py`, `apps/screamingface-engine/src/screamingface_engine/combine/evidence.py`, `packages/screamingface/src/screamingface/answer.py`, `packages/screamingface/src/screamingface/combine_evidence.py`, `packages/screamingface/src/screamingface/_evaluation/combine_evidence.py`, `packages/screamingface/src/screamingface/report.py`, the pinned files P-1 to P-4, and this ledger.
- **Commits:** A `cd9c8bcf5` (RED). B: the GREEN commit, message `feat(e4b): the excluded status, the rank and the cut in the combine evidence (part 2 unit 1)`.
- **Gates** (`run_gates.py <stack> --base 0f4b9e292`):
  - `screamingface-engine`: green with `--skip-append-only`. ruff check, ruff format, pyright, layering and pytest with coverage pass. Append-only check fails and lists exactly P-1.
  - `screamingface`: green with `--skip-append-only`. ruff check, ruff format, pyright, pytest with coverage (95 %), notebooks, build and distribution check pass. Append-only check fails and lists exactly P-2, P-3 and P-4.
  - `repo`: green (append-only check passes for this stack).
  - Focused tests (plan §5.2) pass: engine 199 and 187 for the two lists; SDK pass; `test_combine_evidence_words.py` 35 and `test_evidence_words.py` 38 pass (all RED tests of this unit are green).
  - No flaky test in this run. Retries: 0.
- **RED log:** Run at commit A (base `ad443b3f4` plus the RED files).
  - Engine `tests/unit/test_combine_evidence_words.py`: 28 passed (ES#1, CHAR, 28 cases), 7 failed.
    Failing tests: `test_answer_record_accepts_excluded_with_an_exclude_reason` (ES#2, Literal
    refuses `excluded`), `test_answer_record_refuses_excluded_without_an_exclude_reason` (ES#3,
    Literal refuses `excluded`), `test_answer_record_refuses_an_exclude_reason_on_a_failed_member`
    (ES#4, Literal refuses `excluded`), `test_rank_outside_one_to_scored_count_is_refused` (ES#6,
    extra key `rank` forbidden), `test_cut_k_and_order_are_checked` (ES#7, extra key `cut`
    forbidden), `test_dropped_does_not_count_excluded_members` (ES#9, Literal refuses `excluded`),
    `test_answer_v1_and_evidence_v1_snapshots_match` (ES#14, pinned status enum lacks `excluded`).
  - SDK `tests/test_evidence_words.py`: 28 passed (ES#1, CHAR, 28 cases), 10 failed.
    Failing tests: ES#2, ES#3, ES#4 (`Combine answer row status must be one of answered, fail`),
    ES#6 (same status message), ES#7 (`NotImplementedError: E4b part 2 unit 1: CombineCut`),
    ES#8 (pinned status words lack `excluded`), ES#9 (status message), ES#11 (`unsupported field
    'cut'`), ES#13 (status message from the fixture decode), ES#14 (pinned `answer.v1` snapshot
    differs from the expected P-2 words).
  - No collection error on either side.
  - Pyright on the new test files reports only the words and attributes that GREEN adds
    (`excluded`, `no_signal`, `no_weight`, `rank`, `cut`, `RecordStatus`). The stub and the
    deliberately invalid `CombineCut` inputs add no error.
- **Approval blobs** (`git rev-parse 0f4b9e292:<path>` → after commit B `git hash-object <path>`):
  - P-1 `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`: `c191827c4e963d59b13a77daa8ba9f8eac4f810c` → `454353044494ce12ed269123a9627384a4ce1343`
  - P-2 `packages/screamingface/tests/data/schemas/screamingface.answer.v1.json`: `d179ec29bf6aa230a3019cdd2da955be4c18e87a` → `6524c2d068967d7f3455329323aa9dbd02ca5065`
  - P-3 `packages/screamingface/tests/public_surface_snapshot.json`: `489b8a57e3c20c8038085c80fa06a23fb595c178` → `1d1f27ea7439a13a11a81802633a2cb88256053f`
  - P-4 `packages/screamingface/tests/test_pick_output.py`: `26d21c21f5faf4aaf5f42e9f45a96ecf00a95c27` → `03c12205ca6e56715e55f754c7f5e016ffbe6082`

### Review round 1 (fix commit)

- **Input:** the design review of commit B. Four MINOR findings. No BLOCKER or MAJOR finding.
- **R1-1 (SDK `answer.py` docstring):** the old first INVARIANT line still said that the Literals
  were the E4a words. That line contradicted the mapping that follows it. Fix: the module docstring
  now has the text of unit spec §2.3 step 1. No behavior change. No new test: the words are
  already checked by ES#8 (`"RecordStatus"` and `"ExcludeReason"` in the docstring).
- **R1-2 (process, P-4):** the P-4 edit to `test_pick_output.py` is not in plan §6. The owner
  approval list must name P-4. The orchestrator owns this step. No code change in this unit.
- **R1-3 (Engine `combine/evidence.py` docstring):** the INVARIANT paragraph had a short broken
  line. Fix: the paragraph is re-wrapped to 100 columns. No behavior change.
- **R1-4 (`test_evidence_words.py`, ES#13):** the test `test_trace_extract_entry_carries_the_excluded_status`
  had `@requires_engine_app`, but it reads no Engine file. Fix: the decorator is removed. The test
  is new in commit A (not a pre-existing test), so this is not a weakening. The test now runs in an
  SDK-only install.
- **R1-5 (`sf.Answer` checks):** the reviewer accepted the helper `_check_excluded` (D-2). No change.
- **Pinned edits in this round:** none. P-1, P-2, P-3 and P-4 keep their blobs from commit B.

## Unit 2 — member exclusion (EX#1–18, ES#5, ES#10, ES#12)

Status: done (GREEN commit B on top of RED commit A).

### Intent

A member that a combine rule leaves out gets the record status `"excluded"`. The reason is
`no_weight` or `no_signal`. The rule also applies when the step abstains. The endpoint computes
the rule once from the plan (`_Plan.excludes`) and applies it in `_member_record`. No operator,
no core `Answer` and no Case answer changes. A failed member stays `"fail"`. Both evidence
validators refuse an evidence that chooses an excluded member (CE-I3).
Decisions: Q3, Q4, P1, P2, P3, P4, P5, P13.

### Planned changes

- Engine: `E/combine/ports.py` (`OperatorDescriptor.reads_weights` and its guard),
  `E/combine/operators/reduce.py` (`reads_weights=True` on `weighted_mode@1`,
  `weighted_median@1`, `weighted_mean@1`), `E/combine/endpoint.py` (`_Exclusion`, `_exclusion`,
  `_Plan.excludes`, `_member_record`, `_record_status`), `E/combine/evidence.py` (CE-I3 check).
- SDK: `S/combine_evidence.py` (CE-I3 check `_never_excluded`). See D-2.
- Tests (new): `ET/test_combine_member_exclusion.py`, `ET/test_combine_member_exclusion_world.py`,
  `ST/test_member_exclusion.py`. Appended: `ET/test_combine_evidence_contract_fixture.py`
  (`vote_weight_excluded`, `filter_signal_excluded`), `ST/test_combine_evidence_contract.py`
  (`_EXPECTED_NAMES`, ES#5 test).

### Pinned edits (owner approval)

- X-1 `apps/screamingface-engine/tests/unit/data/combine_contract/evidence_cases.json`
  (regenerated in commit B: two changed cases, two new cases).
- X-2 `apps/screamingface-engine/tests/unit/test_combine_evidence_contract_fixture.py` (append
  only; the gate does not flag it).
- X-3 `packages/screamingface/tests/test_combine_evidence_contract.py` (append only; not flagged).
- X-4 `apps/screamingface-engine/tests/unit/test_combine_weighted_vote.py` line 213: the members
  with no usable weight are `excluded` / `no_weight`, not `answered`.
- X-5 `packages/screamingface/tests/test_frozen_record_fields.py` line 184: 28 becomes 30 cases.
  See D-1.

### Test plan

- 21 rows: EX#1–18, ES#5, ES#10, ES#12 (unit spec section 3).
- CHAR rows first: EX#1 and EX#2 pass on the parent. ES#10 passes at commit A (unit 1 delivered
  the decoder). GUARD rows EX#11 and EX#12(a) pass at commit A and must stay green.
- RED stubs: `OperatorDescriptor.reads_weights` (field only) and `endpoint._exclusion` (returns
  None, not wired into `_plan`). Every other RED row fails on the behavior.
- Oracles are computed by hand (unit spec sections 2.9 and 3). Example: the X1 tally "a" is
  0.9 + 0.4 = 1.3. The weighted median of 3 (0.3), 7 (0.3), 9 (0.4) is 7.

### Acceptance

- In a weighted vote by `field:confidence`, a member without confidence is `excluded` /
  `no_weight` and keeps its value. The answer does not change (EX#4, EX#5).
- A Pick, Rank or Filter by a signal shows a member without the signal as `excluded` /
  `no_signal`. A Filter member keeps mark 0 (EX#6, EX#7, EX#9).
- When every member is left out, the step abstains and every record is `excluded` (EX#5, EX#8).
- A failed member stays `"fail"` (EX#10). Authored weights and unweighted operators never
  exclude (EX#11, EX#12).
- Only `rank_cut_not_met` and `mean_weighted_value` change in `evidence_cases.json`, plus the two
  new cases. No schema snapshot, no url4 file and no golden operator fixture changes.

### Deviations

- D-1: `ST/test_frozen_record_fields.py::test_fixture_answers_and_traces_use_the_frozen_fields`
  pins the number of engine fixture cases (28). The two new cases make it 30. This pinned edit
  (X-5) is not in plan section 6. Unit 3 changes this count again.
- D-2: plan section 2 lists no SDK file for unit 2, but PRD row EX#14 asks for the CE-I3 check
  "on both sides". `S/combine_evidence.py` gets `_never_excluded`.
- D-3: PRD EX-1 says member 3 has `value: "B"`. With the `text@1` normalizer the value is `"b"`
  and the raw is `"B"`. The tests use the exact engine values.
- D-4 (review round 1): PRD row EX#3 asks for a property over the goldens and over
  `evidence_cases.json`. The unit spec narrows it to the SCENARIOS (`evidence_cases.json`). The
  operators do not change, so the golden operator suite still guards the goldens.
- D-5 (review round 1): PRD row EX-D8 asks that the quorum and the coverage counts do not change.
  The evidence does not expose a quorum or a coverage field. The test
  `test_dropped_and_quorum_ignore_excluded_members` checks `dropped` only. No assertion was added.
- D-6 (review round 1): the test name `test_sdk_run_shows_excluded_member_in_case_answers` comes
  from the PRD and is kept. The test checks the engine run record. The SDK `case.answers()` view is
  checked by `ST/test_member_exclusion.py::test_case_answers_show_the_excluded_status_and_value`.
- D-7 (review round 1): the RED commit subject is `test(screamingface-engine): RED for E4b part 2
  unit 2 member-exclusion`. Spec section 7 names a different subject. The history is not rewritten.
- Owner approval, X-5: the owner must approve X-5 (`test_frozen_record_fields.py`, line 184,
  28 to 30) together with X-1, X-2, X-3 and X-4. Unit 3 changes this count again.

### Outcome (fill at the end — required before COMMIT)

- **Status:** done. The code is GREEN. Engine and SDK gates pass, except the append-only check. The
  owner must approve the pinned edits before the part can merge.
- **Actual files:** `E/combine/ports.py` (`reads_weights` field and guard), `E/combine/operators/reduce.py`
  (`reads_weights=True` on `weighted_mode@1`, `weighted_median@1`, `weighted_mean@1`),
  `E/combine/endpoint.py` (`_Exclusion`, `_exclusion`, `_Plan.excludes`, `_record_status`,
  `_member_record`), `E/combine/evidence.py` (CE-I3 check), `S/combine_evidence.py` (`_never_excluded`,
  CE-I3 check; D-2). Regenerated pinned file X-1 `ET/data/combine_contract/evidence_cases.json`.
  No schema snapshot, no `.url4` file and no golden operator fixture changed.
- **Commits:** A (RED) `9b24dd9d9` (the ledger section, the new tests, the stubs, the appends X-2
  and X-3, the edits X-4 and X-5). B (GREEN): the commit that adds this text. No commit C: spec §7
  asks for none in this unit.
- **Gates:** `run_gates.py screamingface-engine --base 0f4b9e292`: the append-only check fails and
  lists X-1 `evidence_cases.json`, X-4 `test_combine_weighted_vote.py` and P-1 (unit 1,
  `screamingface.combine-evidence.v1.json`). The rerun with `--skip-append-only` is ALL GATES GREEN
  (ruff check, ruff format, pyright, layering, pytest with coverage).
  `run_gates.py screamingface --base 0f4b9e292`: the append-only check fails and lists P-2
  (`screamingface.answer.v1.json`), P-3 (`public_surface_snapshot.json`), P-4 (`test_pick_output.py`,
  unit 1) and X-5 (`test_frozen_record_fields.py`). The rerun with `--skip-append-only` is ALL GATES GREEN (ruff check, ruff format, pyright, pytest with coverage, notebooks, build, distribution check).
  `run_gates.py repo --base 0f4b9e292`: ALL GATES GREEN, the append-only check passes.
  Focused engine run (spec §5.2): 577 passed. Focused SDK run (spec §5.2): 127 passed.
- **Hand-run layering check:** `python3 .claude/scripts/check_layering.py` fails under the system
  Python 3.9 (`def accumulate[T: ...]` is a syntax error). Under the project Python 3.13 it prints
  `LAYERING OK`. This is an environment issue, not a code defect. The engine gate uses the venv and
  passes.
- **RED log:** Run at commit A (after the stubs and the RED tests, before the commit).
  - Engine, focused list of unit spec section 5.2 (`pytest -q -rfE`): 22 failed, 553 passed.
    - PASS (CHAR or GUARD, as the table says): EX#1 `test_weighted_vote_drops_a_member_with_no_usable_weight`,
      EX#2 `test_filter_gives_a_missing_signal_mark_zero`, EX#11 `test_authored_weights_never_exclude`,
      EX#12(a) `test_signal_weight_on_an_unweighted_op_never_excludes` (3 cases).
    - FAIL on an assertion (the behavior is not there yet, the status is still `answered`):
      EX#3 (`changed` is an empty set), EX#4, EX#5 (`_rows` lists `answered`), EX#6, EX#7, EX#8, EX#9,
      EX#10 (3 cases), EX#13, EX#15, EX#16 (2 cases), EX#17, EX#18(a) (`DID NOT RAISE ValidationError`),
      EX#12(b) (the set of weighted ops is empty), EX#18 world (`members` status), and the byte-for-byte
      fixture check and count check on the two new scenarios (`KeyError`), and the X-4 line
      (`test_voter_with_missing_or_invalid_weight_signal_does_not_vote`, `assert False`).
    - Row 9(c) (the pattern form) is the third assert of the row 9 test. It is not reached at commit A,
      because (a) fails first. A probe of (c) alone, at commit A, gave pass (`_rows` all answered).
  - SDK, list of unit spec section 5.2 (`pytest -q -rfE`): 7 failed, 118 passed.
    - PASS: ES#10 `test_sdk_decodes_excluded_rank_and_cut` (CHAR), ES#12 second function
      `test_case_answer_of_x1_wire_is_excluded`.
    - FAIL: ES#12 first function (`set()` is not a superset), EX#14 SDK (`DID NOT RAISE ExecutionError`),
      ES#5 (`set()` is not a superset), round trip of the two new names (`KeyError`), the name set
      of the engine fixture (`_EXPECTED_NAMES` has the two new names, the fixture does not yet), and `test_fixture_answers_and_traces_use_the_frozen_fields`
      (`assert 28 == 30`, X-5).
  - No collection error on either side. `ruff check`, `ruff format --check` and `pyright` pass on the
    new and the touched test files. `check_layering.py` prints LAYERING OK.
- **Approval blobs** (`git rev-parse 0f4b9e292:<path>` → `git hash-object <path>` after commit B):
  - X-1 `apps/screamingface-engine/tests/unit/data/combine_contract/evidence_cases.json`:
    `ecf2f814a51548ff56df7a12d2f51fd6beab2b44` → `46fa01af12e63b03b12dba799e9bde29aaf30a45`
  - X-2 `apps/screamingface-engine/tests/unit/test_combine_evidence_contract_fixture.py`:
    `f55477f5d3686514d18ad1cb0f7183c6cb6385cf` → `57a6642a98463becd181db9f5284356c6aa9260a`
  - X-3 `packages/screamingface/tests/test_combine_evidence_contract.py`:
    `fab1c0db10ea4f66ca5f2d8642937d255e7165c4` → `c92903a0a4f8d437f97c9be41e7a2f1e4153b7cb`
  - X-4 `apps/screamingface-engine/tests/unit/test_combine_weighted_vote.py`:
    `e70c69eebbd2fe2333a14c28ddfe69644e19e7de` → `16e266abff3ec3f1b55f952ba1b56922aa37d275`
  - X-5 `packages/screamingface/tests/test_frozen_record_fields.py`:
    `c6b98604a87c661ede9e7b275fd6fbdd455045e1` → `e70218b1864a349f7fc2cf9c0700977c34be2953`
- **Flakes:** none seen in the runs above.
- **Process notes:** `ruff format` reflowed one `members=[...]` line in `endpoint.py` before the
  engine gate. This is a format-only change.

### Review round 1 (fix commit)

- **Findings applied:** the RED log is restored in the Outcome (the pointer to commit A is
  replaced). One comment is added to `ET/test_combine_member_exclusion_world.py`, above the test
  that keeps the PRD name. The comment names the SDK half of the row (ST/test_member_exclusion.py).
- **Findings not applied, no change:** the optional quorum or coverage assertion (EX-D8), because
  no such field is exposed (D-5). The `_exclusion` duplicate read (P13 pins it). The shared
  helper copies in the tests (the spec allows all three copies). The commit subject (D-7). The
  narrower EX#3 scope (D-4, documented).
- **Behavior change:** none. No test was added, weakened or removed in this round. No pinned
  file changed in this round.
- **Gates (this round):** `run_gates.py screamingface-engine --base 0f4b9e292`: the append-only
  check lists X-1, X-4 and P-1 (the same files as before). `--skip-append-only`: ALL GATES GREEN.
  `run_gates.py screamingface --base 0f4b9e292`: the append-only check lists P-2, P-3, P-4 and X-5.
  `--skip-append-only`: ALL GATES GREEN. `run_gates.py repo --base 0f4b9e292`: ALL GATES GREEN,
  the append-only check passes.
- **Flakes:** none in this round.

## Unit 3 — rank and cut of a top-k step (`rank`, `cut`)

### Intent

This unit adds the rank and the cut of a `top_k@1` step. A `top_k@1` step writes the 1-based
ordinal `rank` of each member that has a score. The evidence also writes the `cut` (`k`, and
`order` with the default `"max"` filled in), also on an abstain. The rank and the cut come from
one ordering function, `_ranked`, which `top_k` also uses. So `chosen` is always the members with
`rank <= cut.k`, in rank order. No other step writes the keys, so their evidence keeps its v1
bytes. No Case answer, no combine spec and no url4 file changes.

PRD `rank-and-cut`, rows RK#1 to RK#13, and guard RK-N1. Decisions: P6, P7, P11, P14, Q3, Q4.

### Planned changes

- `E/combine/ports.py`: `OperatorDescriptor.ranks` and `.cut` (select only, not published).
- `E/combine/operators/selection.py`: `_ranked` (the shared order). `top_k` uses it. `top_k_ranks`
  and `top_k_cut` are registered on `top_k@1`.
- `E/combine/endpoint.py`: `_Plan.ranks`, `_Plan.cut`, `_cut`. `_evidence` writes `rank` and
  `cut`. `_member_record` takes `rank=`.
- New tests: `ET/test_combine_rank_cut.py`, `ET/test_combine_rank_cut_world.py`,
  `ST/test_combine_rank_cut.py`.
- Pinned edits (owner approval): `ET/data/combine_contract/evidence_cases.json` (regenerated).
  `rank_by_judge`, `rank_by_signal` and `rank_cut_not_met` gain `rank` and `cut`. New cases
  `rank_min_cost` and `rank_reduce_abstain`. `ET/test_combine_evidence_contract_fixture.py` (two
  scenario functions and two registrations). `ST/test_combine_evidence_contract.py` (one line in
  `_EXPECTED_NAMES`).

### Test plan

- 13 PRD rows, RK#1 to RK#13, in the PRD order, plus guard RK-N1. CHAR: RK#1. RED: the others.
  RK#13 has an engine half (run of `recipe_s10.url4`) and an SDK half (decode of `rank_min_cost`).
- Stub (commit A): the two `OperatorDescriptor` fields only, with no check. Each RED test fails on
  a value or on `DID NOT RAISE`. No RED test fails on an import error.
- Invariants: ranks are 1..n over the scored members, ordinal, author order on ties. The cut is
  written also on an abstain. Evidence of a step other than `top_k@1` keeps its bytes. Every
  expected rank is computed by hand (PRD RK-1 to RK-3 and the RK#5 oracle).

### Acceptance

- `sf.Rank(2, by_signal=sf.signal("cost_usd"), order="min")` with costs 0.03, 0.01, 0.02, 0.01
  gives ranks 4, 1, 3, 2, `chosen` `[member_2, member_4]` and `cut` `{"k": 2, "order": "min"}`.
- A `cut_not_met` abstain writes the ranks of its scored members and the cut.
- An unscored member has no `rank` key. No step other than `top_k@1` writes `rank` or `cut`.
- `evidence_cases.json` changes only in the three rank cases, plus the two new cases. The diff
  check of the plan passes.
- Engine and SDK gates are green, except the append-only check. That check lists only the plan
  section 6 files of units 1 to 3. The `repo` gate is green.

### Outcome (fill at the end — required before COMMIT)

- **Status:** DONE. The GREEN code is written. The owner approved the one-line count edit
  (D-3, 2026-10-15). All three stacks are green, except the append-only check of the two stacks
  that have pinned edits (see Gates). Commit B holds the code, the regenerated fixture, the count
  edit and this ledger text.
- **Actual files:**
  `apps/screamingface-engine/src/screamingface_engine/combine/ports.py` (one select-only check,
  one docstring sentence),
  `apps/screamingface-engine/src/screamingface_engine/combine/operators/selection.py` (`_ranked`,
  `top_k_ranks`, `top_k_cut`, descriptor hooks), `apps/screamingface-engine/src/screamingface_engine/combine/endpoint.py`
  (`_Plan.ranks`, `_Plan.cut`, `_cut`, `_evidence`, `_member_record`),
  `apps/screamingface-engine/tests/unit/data/combine_contract/evidence_cases.json` (pinned, regenerated
  by the script of the spec §5; the diff check passes), and this ledger.
- **Commits:** A `a7abc2639` (RED), B `e1e40d793` (GREEN); base 92cf6011e.
- **Gates** (`run_gates.py <stack> --base 0f4b9e292`):
  - `screamingface-engine`: append-only check FAILS. It lists `evidence_cases.json` (this unit,
    pinned), `combine-evidence.v1.json` (unit 1, P-1) and `tests/unit/test_combine_weighted_vote.py`
    (unit 2 RED commit `9b24dd9d9`, not this unit). Rerun with `--skip-append-only`: ALL GATES
    GREEN (ruff check, ruff format, pyright, layering, pytest with coverage).
  - `screamingface`: append-only check FAILS. It lists `answer.v1.json` (P-2), `public_surface_snapshot.json`
    (P-3), `tests/test_pick_output.py` (P-4), all unit 1, and `tests/test_frozen_record_fields.py`
    (unit 2 RED commit `9b24dd9d9`). Rerun with `--skip-append-only`: ruff, format and pyright
    pass. pytest: 4300 passed, 32 skipped, 1 FAILED (see D-3). Coverage 97.04 %.
  - `repo`: ALL GREEN (append-only check passes for this stack).
  - Focused tests: engine `test_combine_rank_cut.py` and `test_combine_rank_cut_world.py` 50 passed;
    the plan §5 engine group 539 passed; ES#1 (`evidence_without_new_values_keeps_v1_bytes`) and
    EX#3 (`case_answers_do_not_change_with_exclusion`) pass; `test_combine_evidence_contract_fixture.py`
    32 passed. SDK `test_combine_rank_cut.py`, `test_combine_evidence_contract.py`,
    `test_evidence_fixture_agreement.py`, `test_combine_evidence.py`: 84 passed.
  - No flaky test in this run. Retries: 0 for the code. The known flaky tests of OME-1619 did not fail.
  - Rerun after the review fixes (D-4, ledger text): the same results. `screamingface-engine`:
    append-only check FAILS on the same 3 files; with `--skip-append-only` ALL GATES GREEN.
    `screamingface`: append-only check FAILS on the same 4 files; with `--skip-append-only` ruff,
    format and pyright pass, pytest 4300 passed, 32 skipped, 1 FAILED
    (`test_fixture_answers_and_traces_use_the_frozen_fields`, `assert 32 == 30`, D-3), coverage
    97 %. `repo`: ALL GATES GREEN. No flaky test.
  - Final run (the tree of commit B, 2026-10-15). `screamingface-engine`: append-only check
    lists 3 files (`evidence_cases.json`, the pinned data of unit 3; `combine-evidence.v1.json`,
    P-1; `tests/unit/test_combine_weighted_vote.py`, D-2). With `--skip-append-only`: ALL GATES
    GREEN. `screamingface`: append-only check lists 4 files (`answer.v1.json`, P-2;
    `public_surface_snapshot.json`, P-3; `tests/test_pick_output.py`, P-4;
    `tests/test_frozen_record_fields.py`, D-2 and D-3). With `--skip-append-only`: ALL GATES
    GREEN, pytest green with the count at 32. `repo`: ALL GREEN, no skip. Focused: `test_combine_rank_cut.py`,
    `test_combine_rank_cut_world.py`, `test_combine_evidence_contract_fixture.py`: 85 passed. ES#1
    and EX#3: 33 passed (`-k` run over the two files). The diff check of plan §5 step 5 passes.
    No flaky test.
- **RED log:** commit A `a7abc2639` was re-run from an exported copy (`git archive`), with the
  venvs of this worktree. No RED test fails on an import error. RK#1 passes (CHAR).
  - Engine, 24 failed, 61 passed (`test_combine_rank_cut.py`, `test_combine_rank_cut_world.py`,
    `test_combine_evidence_contract_fixture.py`):
    - `test_ranks_follow_the_top_k_order_for_min`: `assert [None, None, None, None] == [4, 1, 3, 2]`
    - `test_ranks_and_tie_for_max_with_equal_scores_at_the_cut`: `assert [None, None, None] == [1, 2, 3]`
    - `test_cut_writes_k_and_the_default_order`: `KeyError: 'cut'`
    - `test_chosen_equals_members_ranked_within_k`: `KeyError: 'cut'`
    - `test_judge_scored_rank_has_ranks`: `assert [None, None, None] == [3, 1, 2]`
    - `test_cut_not_met_still_writes_ranks_and_cut`: `assert [None, None, None] == [2, None, 1]`
    - `test_unscored_member_has_no_rank_key[failed]`, `[excluded]`: `assert [None, None, None] == [2, None, 1]`
    - `test_a_failed_member_with_a_judge_score_keeps_its_rank`: `assert [None, None] == [2, 1]`
    - `test_steps_other_than_top_k_keep_their_bytes` (RK#9), the 5 rank scenarios only
      (`rank_by_judge`, `rank_by_signal`, `rank_cut_not_met`, `rank_min_cost`,
      `rank_reduce_abstain`): `assert ('cut' in {...}) is True`
    - `test_k_equal_to_scored_count_chooses_all`: `assert [None, None, None, None] == [3, None, 1, 2]`
    - `test_all_equal_scores_rank_in_author_order[max]`, `[min]`: `assert [None, None, None, None] == [1, 2, 3, 4]`
    - `test_reduce_abstain_writes_cut_without_ranks[reduce_abstains]`, `[no_voter]`: `KeyError: 'cut'`
    - `test_only_a_select_operator_may_declare_ranks_or_a_cut` (RK-N1): `Failed: DID NOT RAISE ValueError`
    - `test_combine_rank_cut_world.py::test_sdk_rank_recipe_run_writes_rank_and_cut` (RK#13a):
      `assert [None, None, None] == [3, 1, 2]`
    - `test_the_engine_evidence_is_the_fixture_byte_for_byte[rank_min_cost]`, `[rank_reduce_abstain]`:
      `KeyError` on the case name
    - `test_the_fixture_holds_exactly_the_scenarios`: the scenario lists differ
  - SDK, 4 failed, 31 passed (`test_combine_rank_cut.py`, `test_combine_evidence_contract.py`):
    - `test_sdk_reads_rank_and_cut_from_a_rank_run` (RK#13b): `AssertionError: regenerate
      evidence_cases.json (E4b part 2 unit 3)`
    - `test_the_engine_fixture_holds_the_25_scenarios`: the `_EXPECTED_NAMES` set differs
    - `test_an_engine_evidence_decodes_and_round_trips_exactly[rank_min_cost]`,
      `[rank_reduce_abstain]`: `KeyError` on the case name
  - After the GREEN code, all these tests pass. Pyright and ruff are clean in both stacks.
- **Deviations:** (pre-filled) D-1: plan §6 names only `rank_cut_not_met` among the changed
  evidence cases. `rank_by_judge` and `rank_by_signal` are `top_k@1` steps too, so P6 and P7 make
  them gain `rank` and `cut` as well. The pinned file is the same.
  - D-2: the append-only offenders `tests/unit/test_combine_weighted_vote.py` (engine) and
    `tests/test_frozen_record_fields.py` (SDK) were changed by the unit 2 RED commit `9b24dd9d9`.
    This unit did not change them. Plan §6 covers them under the unit 2 catch-all.
  - D-3 (APPROVED by the owner, 2026-10-15): `packages/screamingface/tests/test_frozen_record_fields.py`,
    line 184, function `test_fixture_answers_and_traces_use_the_frozen_fields`: the literal
    `len(wires) == 30` becomes `len(wires) == 32`. This is the smallest edit (one line). The
    fixture holds 32 cases (2 new rank cases), so the assertion is true. The spec did not list
    this file as a pinned edit. The owner standing rule (2026-10-15) applies to later units: when
    a unit adds evidence cases, the case-count literal in this line may be bumped by one line,
    and the bump is reported as a pinned edit.
  - D-4 (review fix): spec §2.3 item 2 asks for a sentence in the `_Plan` docstring. The first
    GREEN pass used an inline field comment. The review fix moves the text into the `_Plan`
    docstring, as the spec says: "``ranks`` and ``cut``: the hooks of a select step that ranks
    (``top_k@1``); the cut is read once from the checked args." The inline comment is removed.
  - D-5 (review note): the PRD §4 NFR says "the ranks reuse the one sort of top_k@1". The code
    shares one ordering function, `_ranked`, and does not share one sort: `top_k` and
    `top_k_ranks` each sort once per call. The unit spec chose this design. It stays
    O(n log n) for n <= 256. No change.
  - D-6 (review note): neither commit uses the spec §7 subject text. Spec §7 gives
    `test(e4b): RED for rank and cut of a top-k step (part 2 unit 3)` for commit A and
    `feat(e4b): write the rank and the cut of a top-k step in the combine evidence (part 2 unit 3)`
    for commit B. The actual subjects are `test(screamingface-engine): RED for E4b part 2 unit 3
    rank-cut` (commit A) and `feat(e4b): rank and cut in the combine evidence (E4b part 2 unit 3)`
    (commit B). The subjects are not amended.
- **Approval blobs** (for each pinned file: blob at `0f4b9e292`, blob at the unit 2 tip `92cf6011e`,
  blob at commit B `e1e40d793`):
  - `apps/screamingface-engine/tests/unit/data/combine_contract/evidence_cases.json`: `ecf2f814a51548ff56df7a12d2f51fd6beab2b44` → `46fa01af12e63b03b12dba799e9bde29aaf30a45` → `22d54b15b8c5d8f312b1a962ef6f590b61aa4791`
  - `apps/screamingface-engine/tests/unit/test_combine_evidence_contract_fixture.py`: `f55477f5d3686514d18ad1cb0f7183c6cb6385cf` → `57a6642a98463becd181db9f5284356c6aa9260a` → `b7100e62690d9dd01432ae599547906618924c4e`
  - `packages/screamingface/tests/test_combine_evidence_contract.py`: `fab1c0db10ea4f66ca5f2d8642937d255e7165c4` → `c92903a0a4f8d437f97c9be41e7a2f1e4153b7cb` → `3aaa863684aa156cd2b80e0bcd30e08d33c406fd`
  - `packages/screamingface/tests/test_frozen_record_fields.py` (D-3, line 184): `c6b98604a87c661ede9e7b275fd6fbdd455045e1` → `e70218b1864a349f7fc2cf9c0700977c34be2953` → `b0f1493ec8e1616c733b193f14b7c8ef280234b8`

### Review round 1 (fix commit)

- **Input:** the design review of commit B. Three MINOR findings that concern the ledger text, and
  four optional or informational notes. No BLOCKER, MAJOR or behavior finding.
- **Applied (ledger only):**
  - The Commits line is set to commit A `a7abc2639` (RED), commit B `e1e40d793` (GREEN), base
    `92cf6011e`. The stale wording "uncommitted" and "B: not made" is removed.
  - The approval blob line for commit B now reads "blob at commit B `e1e40d793`".
  - D-6 now names the spec §7 subjects and the actual subjects. Neither commit is amended.
  - The approval blob list has an entry for `packages/screamingface/tests/test_frozen_record_fields.py`
    (D-3). The blobs are `c6b98604…` at the base, `e70218b1…` at the unit 2 tip and `b0f1493e…`
    at commit B.
- **Not applied, no change:**
  - The optional `RankOp` alias for the hook type in `ports.py` and `endpoint.py`. The hook
    signature is short, and both uses are in one unit. A later unit may add the alias.
  - The `_cut` read order in `_plan`. The WHY comment documents the order, and the spec asks for
    this shape. No later unit touches `_plan` in this part.
  - The PRD NFR wording "one sort of top_k@1" (D-5). The code shares one ordering function. The
    wording is left for a later docs pass.
  - The `_ranked` double sort (D-5). Its cost is negligible for n <= 256.
- **Behavior change:** none. No code, test or pinned data file changed in this round.
- **Pinned edits in this round:** none. The four blobs of commit B stay as listed above.
- **Gates (this round, `run_gates.py <stack> --base 0f4b9e292`):**
  - `screamingface-engine`: the append-only check fails and lists the same 3 files
    (`evidence_cases.json`, P-1 `combine-evidence.v1.json`, `test_combine_weighted_vote.py`, D-2).
    With `--skip-append-only`: ALL GATES GREEN (ruff check, ruff format, pyright, layering, pytest
    with coverage).
  - `screamingface`: the append-only check fails and lists the same 4 files (P-2, P-3, P-4 and
    `test_frozen_record_fields.py`, D-2 and D-3). With `--skip-append-only`: ALL GATES GREEN (ruff
    check, ruff format, pyright, pytest with coverage, notebooks, build, distribution check).
  - `repo`: ALL GATES GREEN, the append-only check passes.
- **Flakes:** none in this round.

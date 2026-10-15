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

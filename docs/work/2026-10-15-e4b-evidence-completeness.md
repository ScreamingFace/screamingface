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
  pinned edit (P-4) that plan §6 did not list.

### Outcome (fill at the end — required before COMMIT)

- **Status:** RED committed (commit A). GREEN (commit B) is not yet done.
- **Actual files:** commit A: the ledger, `apps/screamingface-engine/tests/unit/test_combine_evidence_words.py`, `packages/screamingface/tests/test_evidence_words.py`, the `CombineCut` stub in `packages/screamingface/src/screamingface/combine_evidence.py`.
- **Commits:** A (RED, see the git log of the branch), B pending.
- **Gates:** pending (filled at commit B).
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
- **Approval blobs:** pending (filled at commit B).

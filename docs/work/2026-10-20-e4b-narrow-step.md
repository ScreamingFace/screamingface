---
ticket: OME-1653
stack: screamingface-engine
status: done
started: 2026-10-20
finished: 2026-10-20
---

# e4b-narrow-step — narrow steps before the reduce in one combine call (unit 1)

## Intent

The map → select → reduce surface (spec `docs/spec/2026-10-20-e4b-mapreduce-surface/`) lets a
recipe narrow the panel (`sf.Filter`, `sf.Rank`) before its reducer, as in
`Fanout >> Filter(...) >> Mean()` and `Fanout >> Rank(k=3, ...) >> Vote()` (owner answer A2). This
unit adds that capability to the Engine combine call: an optional spec key `narrow` (1 to 4 narrow
steps), the per-step one-signal rule, the judged set of `scores@1`, the evidence `narrow` record
and the exclude reason `not_selected`, and the SDK decoder of that evidence. A spec without
`narrow` keeps its evidence bytes.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/combine/spec.py`: `NarrowSpec`,
  `NARROW_RULES`, `MAX_NARROW_STEPS`, the stage rules NR-S1 and NR-S2b, `CombineSpec.narrow`.
- `.../combine/endpoint.py`: `_NarrowPlan`, `_narrowed`, the narrow pair rule (NR-S2), the
  per-step signal rule (NR-S3), the places of narrow.md §5 on the Engine side.
- `.../combine/ports.py`: `ExcludeReason` gets `not_selected`; `CombineInput.judged`.
- `.../combine/operators/judge.py`: `scores@1` parses the reply over the judged set, then keeps
  the scores of the live members.
- `.../combine/evidence.py`: `NarrowRecord`, `CombineEvidence.narrow`, NR-I1..NR-I6, AR-I3′.
- SDK `packages/screamingface/src/screamingface/`: `combine_evidence.py` (`CombineNarrow`,
  `CombineEvidence.narrow`), `_evaluation/combine_evidence.py` (decode the optional key),
  `answer.py` (`not_selected`).
- New contract data `apps/screamingface-engine/tests/unit/data/combine_contract/narrow_evidence_cases.json`.
- Pinned (owner approval): the spec and evidence v1 schema snapshots, the SDK public surface
  snapshot.

## Test plan

- `ET/test_combine_narrow_spec.py`: NR-1, NR-2, NR-3, NR-10d (spec rules NR-S1, NR-S2, NR-S2b, NR-S3).
- `ET/test_combine_narrow.py`: NR-4..NR-10, NR-10b, NR-10c; the contract file pinned byte for byte.
- `ET/test_combine_narrow_evidence.py`: NR-11 (NR-I1..NR-I6, AR-I3′ refuse bad records).
- `ST/test_narrow_evidence_words.py`: NR-13, NR-14 (SDK decode, `not_selected`).
- NR-12: the existing contract tests pass with no edit.

## Acceptance

- Each NR-S and NR-I rule has one Engine test; the SDK decodes every case of
  `narrow_evidence_cases.json` and an evidence with no `narrow` key decodes with `narrow is None`;
  a spec without `narrow` gives byte-identical evidence; the three stacks' gates pass, with the
  append-only check flagging only the three pinned files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `E/combine/operators/judge.py` (judged set),
  `S/report.py` (`CombineNarrow` public on `sf.report`), the test support module
  `ET/combine_narrow_support.py`. No `S/_evaluation/combine_spec.py` change (evidence decoding
  does not need the spec; the SDK compile of `narrow` is unit 5).
- **Commits:** 7b7ce8918 test (RED); eb16c51c6 feat (GREEN); 3616409be refactor (docstrings);
  2340cc7ea test (SDK twin of NR-I1..NR-I5); this ledger commit.
- **Gates:** repo: ALL GATES GREEN. Engine: ruff, format, pyright, layering green; pytest
  `2 failed, 6470 passed, 122 skipped`, coverage 95.74%. SDK: ruff, format, pyright green; pytest
  `4 failed, 4933 passed, 33 skipped`, coverage 97.17%; notebooks, build, distribution green.
  Every failure is an existing test that pins a word list or a field order that this spec
  changes (see Deviations). The append-only check flags exactly the three pinned files.
- **Deviations:**
  - Existing tests that must change (not edited, owner decision): Engine
    `test_combine_evidence_words.py::test_answer_v1_and_evidence_v1_snapshots_match` (the
    exclude reason list gets `not_selected`) and
    `test_combine_consistency_words.py::test_evidence_with_every_optional_key_orders_cut_consistency_declared_gate`
    (pins `cut` right before `consistency` in the model; narrow.md §4.2 puts `narrow` there);
    SDK `test_band_words.py::test_sdk_reason_words_equal_the_engine_enum_with_in_band`,
    `test_evidence_words.py::test_sdk_record_words_equal_the_evidence_schema_enums`,
    `test_gate_words.py::test_sdk_reason_words_equal_the_engine_enum` (each pins 14 reasons; now
    15) and `test_frozen_record_fields.py::test_sdk_records_match_frozen_field_sets[answer]`
    (needs a fourth pinned file, `ST/data/schemas/screamingface.answer.v1.json`, regenerated;
    then `test_evidence_words.py::test_answer_v1_and_evidence_v1_snapshots_match`,
    `test_pick_output.py::test_answer_v1_lists_output_missing` and
    `test_band_words.py::test_evidence_and_answer_snapshots_hold_the_band` pin its old list).
  - The main step's `Answer.signals` keep only the main key (I-S3); each narrow step's answers
    hold only that step's key. Every key any step reads is in the member rows (narrow.md §4.1).
  - A narrow filter record carries `scores` (the 0/1 pass marks), as a main filter step writes
    them as row scores; the narrow.md §4.2 example leaves them out.
  - A narrow abstain marks every member live at that step as left out by it (`kept: []`); a
    narrow spec with no voter records its first step with `kept: []` and does not run it.
  - NR-S3 inside one narrow item holds by shape (no `weights` key); the judge-source part of
    NR-S2 is a parse rule, the pairs are a plan rule.
  - Not done (spec silent): the Engine does not refuse `label@1`, `field_rules@1` or a judge or
    writer gate after a narrow step (NR-C1 is an SDK rule); evidence `operators` lists the main
    step's ops only.

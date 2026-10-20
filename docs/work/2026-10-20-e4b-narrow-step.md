---
ticket: OME-1653
stack: screamingface-engine
status: in_progress
started: 2026-10-20
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

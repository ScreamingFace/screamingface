---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
---

# e4a-gap-closure unit 3 -- Engine wiring and evidence: abstain mark, grade replacement, answer rules

## Intent

Fold the engine part of the E4a gap-closure on top of the unit 1 core and the unit 2 operators.
When the expression's final node is a combine that abstained, the Candidate Invocation carries
`abstained: true` with an empty answer. The mark travels through the Case records, the grader still
runs on the empty answer, and the Case is scored 0.0 (keeping the grader's metrics and checks).
GSM8K and AIME declare an `answer_rule` in the benchmark catalog. The branch is rebased onto
`e4a-answer-operators`; one repair commit moves a key-order test onto the core's new evidence fields.

## Planned changes

- Rebase repair (Commit B): `test_combine_evidence_wire.py` key order adds `signal`, `result`, `dropped`.
- `benchmarks/contract.py`: `abstained` on `CandidateInvocation` and `CaseResult` (last field, only when true).
- `benchmarks/operation_outputs.py`, `benchmarks/invocation.py`: `final_operation_abstained` and the mark.
- `benchmarks/grading_endpoints.py`, `case_records.py`, `shared_grading/serving.py`, `ifeval/runtime.py`,
  `ifeval/grade.py`, `contracteval/aggregate.py`, `medxpert/aggregate.py`, `healthbench/case_grade.py`,
  inspect `single_shot.py`: carry `candidate_abstained` through the records.
- `benchmarks/aggregation.py`, `shared_grading/benchmark_aggregation.py`: score 0.0 for an abstained Case.
- `benchmarks/definition.py`, inspect `benchmarks.py`, `single_shot.py`: `AnswerRule` for GSM8K and AIME.

## Test plan

A: this ledger. B: key-order repair, no RED. C: rows 1-3 (RX#10), guards, green at once.
D: rows 4-5 (GP#16, GP#8). E: rows 6-10 (AB#9, AB#10, AB#14 invocation half, AB#15).
F: rows 11-12 (AB#9 carry). G: rows 13-20 (AB#14 Case half, AB#18, AB#21-22, AB#11-13).
H: ledger close.

Rows with no RED by design: Commit B, Commit C (rows 1-3), row 4(b) and the 4(a) cases that
are already enforced by stubs, row 9 (AB#10 guard).

## Notes

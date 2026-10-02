---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
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

Decisions F1-F14 (from the unit spec):

- F1 the rebase onto `e4a-answer-operators` has no textual conflict. The one semantic break (the
  evidence key order now ends `signal`, `result`, `dropped`, `finish_reason`) is repaired in Commit B.
- F2 `GET /v1/operators` is `registry.describe()`, so the new operator ids appear when the rebase
  lands. RX#10 (Commit C, 3 tests) is a guard and is green at once.
- F3 "the final node is a combine" is a rule: the root is an `Expression` whose intent is `Text`
  fully matching `$name`, and exactly one attributed `op_<name>` carries abstain evidence. Probe
  result: url4 parses a bare relative call `/x(a)!'$name'` into an `Expression` with NO intent
  (there is no `RelExpr` root), so row 7 case j uses that string and the intent-is-`None` branch.
- F4 wire keys stay `abstained`; the intermediate records and hoisted `row["case"]` use
  `candidate_abstained: true`, written only when true. ContractEval's own verdict `abstained` is kept.
- F5 "ignored" means the grader still returned metrics or checks. A grading step with no material
  (the ladder grading-failure rung, a hook failure with `metrics={}` and `checks=[]`) keeps the Case
  failed and logs it (`_abstained_grade_kept`). Errata for the orchestrator (docs branch): erd
  section 9 and contract G5 must say this, because a scored Case with `metrics={}` breaks
  `mean_scorer`, `draco_scorer` and the ContractEval confusion matrix.
- F6 `CaseResult.abstained` is not decoded by the SDK yet (`results.py` rejects unknown Case keys).
  An SDK reading an abstained Case from this Engine fails until unit 4 (AB#17). Non-abstained Cases
  are byte-identical. The SDK is not touched here.
- F7 `AnswerRule` is a frozen dataclass of operator-id strings, not part of any revision. The
  inspect lane test (GP#8) resolves each id in `BUILTIN_OPERATORS` at its stage.
- F8 grader strings are literal; GP#8 pins the version suffix to `_inspect_vendor` and the prefix to
  the row's scorer.
- F9 IFEval and GSM8K score 0.0 on `""` anyway; their tests prove the plumbing. The HealthBench test
  (fake judge says MET, grader score would be 1.0) proves the replacement.
- F10 validators: an abstained invocation is completed, empty, with no refusal; an abstained Case is
  scored, empty, with `grade.score == 0.0` and no refusal.
- F11 CorrectiveLoop is unchanged. Each round marks its own record; the loop record (`loop_candidate`)
  never is (row 10, three parts).
- F12 `abstained` is the last field of `CandidateInvocation` and `CaseResult`; the decoder rejects an
  explicit `false`.
- F13 `abstained` never appears on a failed Case.
- F14 HealthBench with a one-item rubric makes one judge call (row 18 counts them).

Run notes:

- The base branch moved after the rebase: `e4a-answer-operators` is now at `d5db863d7` (regex@1
  compiles with RE2 options), and this branch still sits on `77f045a37`. Nothing here depends on it
  (`regex@1` summary and `args_schema` are unchanged by it). The append-only gate run against the
  moved base lists two files this branch never touched (`test_combine_regex.py` changed,
  `test_combine_regex_re2_options.py` missing); that is the base's own commit. Against the true
  merge-base `77f045a37` the list is empty.
- Single-shot GREEN (EI `single_shot.py` check record and `_decode`) landed in Commit G with row 12,
  not in Commit F, so row 12 had its own RED. Commit F covers the rest of spec 2.3.
- MedXpertQA in row 11 is exercised through `serving.candidate_record` and `_decode` (the exact
  calls `medxpert.runtime._check` makes), not through the check route, which needs a full asset
  tree.
- Rows with no RED by design: Commit B; Commit C rows 1-3; row 4(b); row 7 cases b-j and the
  fixture test; row 9 (guard); in row 13 the "key is last" half (the stub field already sits last);
  in row 19 the Case already scored 0.0 by itself (only the `abstained` mark was RED).

Verification:

- `uv run .claude/scripts/run_gates.py screamingface-engine --base e4a-answer-operators --skip-append-only`: ALL GATES GREEN
- same, without `--skip-append-only`, against `e4a-answer-operators` (moved base): append-only offenders
  `test_combine_regex.py`, `test_combine_regex_re2_options.py` (the base's own commit); against
  `--base 77f045a37`: ALL GATES GREEN, no offenders.
- `uv run .claude/scripts/run_gates.py screamingface --base e4a-answer-operators --skip-append-only`: ALL GATES GREEN
- `uv run .claude/scripts/run_gates.py repo`: ALL GATES GREEN
- Inspect lane (`--extra inspect pytest -q tests/unit/inspect`): 612 passed, 0 skipped; GP#8
  (`test_benchmark_answer_rules.py`) and AB#12 (`test_abstain_inspect.py`) passed.
- Whole engine suite with the inspect extra: 5844 passed, 6 skipped (all need a live NATS server, or Linux-only
  `RLIMIT_AS`; none is an Inspect or abstain test).

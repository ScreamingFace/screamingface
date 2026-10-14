# Test plan — E4a deterministic combine (OME-1289)

## 1. Mission and mode

These tests must show three things:
1. The combine step is deterministic.
2. The answer is a member's own text when the rules say so.
3. The evidence that reaches the Report is true.

This document is a plan for later implementation units. It contains no executed results.

## 2. Risk model (rubric: qa-tester decision-rubrics)

| Risk ID | Risk | Likelihood signals | L | I | Level | Planned rigor |
|---|---|---|---|---|---|---|
| R1 | The output depends on hash or dict order, so replays differ | new code, complex logic | M | H | High | property test across hash seeds (FW-3) + unit ties (VT-2, WV-4, JG-5) |
| R2 | The answer is not byte-identical to the chosen member | new code | M | H | High | unit (FW-4, VT-1, JG-4, PM-1) + E2E replay (EV-12) |
| R3 | The evidence is wrong, missing, or attributed to the wrong reducer | integration seam, new code | H | H | High | unit (EV-3…EV-5) + integration (EV-6, EV-10) + E2E (EV-12) |
| R4 | A wire change breaks old envelopes | integration seam | M | H | High | golden characterization (EV-1, SL-1) |
| R5 | Judge prose leaks in as the answer | AI output, new code | M | H | High | fuzz parser (JG-1, JG-2) + negative tests (JG-3) |
| R6 | Samples collapse to one cached answer | integration seam, provider differences | M | H | High | recorded-gateway integration (SM-4) + SDK guard (SM-3, SM-5) |
| R7 | Hostile member text (ReDoS, deep JSON, huge text) | untrusted input | L | H | Medium | hostile-input unit tests (OP-2, OP-9, FW-9, FW-10) |
| R8 | An operator changes behavior without a version bump | new code | M | M | Medium | golden fixtures (OP-1) |
| R9 | The core imports plugins (layering break) | new module | M | M | Medium | layering gate fixtures (FW-13) |
| R10 | The SDK and the engine binding patterns drift | two packages | M | H | High | shared fixture run in both packages (SL-10) |
| R11 | The writer sees more than its field | new code | M | H | High | exact-context unit (PM-6) + compile unit (PM-7) |
| R12 | A selection result is graded as an answer | new rule | M | M | Medium | compile checks (RK-1, RK-2, CC-3) |

## 3. Levels (test pyramid)

- **Unit (most).** Operators, the spec parser, the registry, select logic, SDK compile, and the
  decoders. Engine tests go in `apps/screamingface-engine/tests/unit/`, and SDK tests in
  `packages/screamingface/tests/`.
- **Integration.** The world installs the route (FW-12). The catalog route (FW-14). Attribution
  across a real url4 evaluation (EV-6, EV-10). A recorded-gateway test for samples (SM-4). Judge
  and writer failure paths (JG-9, PM-8).
- **E2E (one).** A GSM8K replay lane with `Fusion(samples(<seed-capable model>, 5), Vote(...))` in
  `packages/screamingface/tests/e2e/`. It pins the expression sha, the case statuses, the failure
  codes, the coverage, the score, and the evidence for case 1 (EV-12). This follows the "five locks"
  rule for replay lanes.

## 4. TDD ground rules

- **RED first.** Write the test, run it, and see it fail for the right reason: an assertion on the
  missing behavior, not an import error. A test that passes at once proves nothing. Fix the test.
- **GREEN minimally.** Write the smallest change that passes.
- **REFACTOR only on green.**
- **Characterization tests** (marked `CHAR`) pin today's behavior and pass on today's code: SL-1,
  SL-2, EV-1, EV-2, SM-1. Write them before any delta test in their PRD.
- **Determinism tests** run the endpoint in subprocesses with `PYTHONHASHSEED` set to 0, 1, 2, …
  19, and compare bytes.
- **No test reads its expected value from the code under test.** The oracles are the ticket text
  (OME-1289), the interview answers, and hand-computed fixtures.

## 5. Build order across PRDs (core-out)

1. operator-framework FW-1 … FW-11, then answer-operators OP-1 … OP-18.
2. combine-evidence EV-1 … EV-5 (engine side).
3. reducer-slot SL-1 … SL-14, then combine-evidence EV-6 … EV-11 and EV-13, EV-14 (SDK side).
4. operator-framework FW-12 … FW-17 (wiring, catalog).
5. majority-vote-and-median VT-1 … VT-14.
6. samples SM-1 … SM-10.
7. weighted-vote WV-1 … WV-9.
8. judge-pick JG-1 … JG-10.
9. pick-and-merge PM-1 … PM-15.
10. rank-keep-k RK-1 … RK-9, then concatenate CC-1 … CC-7.
11. E2E EV-12.

## 6. Not tested (with a reason)

| Item | Reason | Owner | Detection | Revisit when |
|---|---|---|---|---|
| Judge answer quality (does the judge pick well) | It is model judgment, not E4a code. E4a tests the parse and the copy | method author | per-benchmark score in reports | a judge-quality eval epic exists |
| Grader parity on imported boards (Inspect `match`) | Parked by the user | E4a owner | the vote tally disagrees with the grade in reports | grader migration starts (ans:Q7) |
| Studio rendering of reducer recipes | Out of scope (ans:Q5) | Studio owner | Studio errors on url4 with `/ensemble/combine/v1` | Studio support is planned |

## 7. Exit criteria for each implementation unit

- All RED → GREEN tests of the unit pass. The CHAR tests stay green.
- `run_gates.py` passes for the stack.
- The layering gate passes.
- `DECLARED_FAILURE_CODES` conformance passes.

---
ticket: OME-1030
stack: screamingface-engine
status: done
started: 2026-08-28
finished: 2026-08-28
---

# OME-1030 — retain the provider attempt count on operation accounting

## Intent

Review finding on PR #762. Retained accounting explains what an operation *cost* but not
*why*: `$0.50` spent as one provider call and `$0.50` spent as five retried calls produce
byte-identical accounting today. The attempt count is the field that turns a number into an
explanation, and it is the only way to tell "this model is slow" apart from "this route is
flaky" when reading `provider_latency_ms`, which sums latency across every attempt including
failures.

The Gateway already publishes the fact — `usage_accounting.attempts` is the array the
Engine's `complete` gate already validates — so no new Gateway read, timer, or transport is
introduced. The count is payload-free and rides the existing ledgers unchanged.

**Owner decision recorded:** the approved spec (§5), plan (step 3) and task all state "no
attempt counter". The owner reversed that constraint in review on 2026-08-28, on the grounds
that a client-facing Report needs to explain a cost, not just state it. Those three artifacts
are amended in this same unit so the SDLC trail matches the shipped contract.

**Scope decision recorded:** Engine only, at the owner's direction. The matching
`packages/screamingface` decoder field belongs to OME-1032 and is NOT part of this unit.
Until OME-1032 carries it, the Client's strict decoder will reject the new field — the same
rollout coupling OME-1030 already carries for the whole `accounting` contract.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/operation_accounting.py` — add
  `OperationAccounting.provider_attempts: int | None`; sum it in
  `combine_operation_accounting`.
- `apps/screamingface-engine/src/screamingface_engine/runner/accounting.py` — add
  `CallAccounting.attempts`; count well-formed attempts in `read_aigw`; project it in
  `retained_operation_accounting` (zero on a confirmed cache hit, null when not complete).
- `apps/screamingface-engine/tests/unit/test_retained_operation_accounting.py` — new cases.
- `apps/screamingface-engine/tests/unit/test_operation_accounting_contract.py` — wire shape.
- `docs/spec/2026-08-27-OME-901-operation-accounting.md`,
  `docs/plan/2026-08-27-OME-901-operation-accounting.md`,
  `docs/tasks/2026-08-27-OME-1030-engine-operation-accounting.md` — record the reversal.

## Test plan

RED first, in this order:

1. **Happy path** — complete Gateway evidence with two attempts retains `provider_attempts: 2`
   in the full `model_dump()` wire shape.
2. **Boundary — several tool rounds** — two combined rounds of 2 and 1 attempts sum to 3,
   alongside the existing latency sum.
3. **Boundary — confirmed cache hit** — no provider dispatch means `provider_attempts == 0`,
   consistent with the existing `cost_usd == "0"` and `provider_latency_ms == 0`.
4. **Error path — not complete** — `capture_status="partial"`, `omitted_attempts=1`, and a
   malformed (non-mapping) attempt each leave `provider_attempts` null rather than counting a
   list the Engine could not validate.
5. **Error path — no Gateway accounting at all** — the narrow provider-usage fallback keeps
   `provider_attempts` null; it is never defaulted to 1.
6. **Invariant — absence is contagious** — combining a round whose accounting is null yields
   null overall, unchanged.
7. **Contract** — the strict wire model rejects a negative count and still forbids unknown
   fields.

## Acceptance

- `provider_attempts` appears in `OperationAccounting`'s wire shape as a required,
  nullable, non-negative integer.
- Exact-only holds: the count is retained only when the Engine validated every attempt.
- No change to `provider`, `request_model`, `response_model`, `usage`,
  `provider_latency_ms`, `cache`, root/live `Usage`, scores, or model-call cardinality.
- `python3 .claude/scripts/run_gates.py screamingface-engine` green.
- Spec, plan and task record the owner-approved reversal.

## Outcome

- **Actual files:** as planned, plus five prior test fixtures that construct or assert the
  full `OperationAccounting` wire shape and therefore had to carry the new required field:
  `test_retained_operation_accounting.py`, `test_gdpval_runtime.py`,
  `test_grading_accounting.py`, `test_healthbench_runtime.py`,
  `test_operation_output_capture.py`, `test_draco_case_artifacts.py`.
- **Commits:** `feat(screamingface-engine): retain the provider attempt count`
- **Gates:** `python3 .claude/scripts/run_gates.py screamingface-engine --skip-append-only`
  — ALL GATES GREEN. Ruff check, Ruff format, Pyright, layering, and 2,235 passed / 5 skipped
  at 91.50% coverage.
- **Deviations:**
  1. **Prior tests extended, never weakened.** Adding a required nullable field to a closed
     wire model necessarily changes every fixture that constructs it or asserts its complete
     `model_dump()`. Each edit ADDS one asserted field; no assertion was deleted, relaxed, or
     skipped. This is the same shape of prior-test update the parent PR already carries with
     explicit owner approval.
  2. **The DRACO end-to-end expectation was a free cross-check.** Its fake Gateway returns no
     `_aigw` envelope at all, so the vertical slice independently confirms the fallback path
     yields `provider_attempts: None` rather than a defaulted 1 — the same invariant the new
     unit test pins.
  3. **Spec/plan/task amended in this unit** to record the owner's reversal of the "no attempt
     counter" constraint, so the approved artifacts match the shipped contract.
  4. **Client decoder deliberately untouched.** `packages/screamingface`'s strict
     `OperationAccounting` will reject `provider_attempts` until OME-1032 adds it. Owner chose
     Engine-only scope; the required client change is a one-line field, one `to_dict` entry,
     and one `__post_init__` validation mirroring `provider_latency_ms`.

---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine, client-sf, url4-sdk
status: done
started: 2026-10-20
finished: 2026-10-20
---

# url4-benchmark-expression — a spec-faithful URL4 expression for imported boards and MedXpertQA

## Intent

Rebuild the Benchmark expression so it reads as URL4 Parts A–C define it: deterministic steps
are RDS code mounts, model calls are LLM mode with the prompt as the quoted intent, the case set
is a data reference, and the nesting is the pipeline. Results, revision ids and model-call bytes
do not change. Spec: `docs/spec/2026-10-20-url4-benchmark-expression-spec.md`. Plan:
`docs/plan/2026-10-20-url4-benchmark-expression-plan.md`.

## Planned changes

- See the plan, Steps 1–5.

## Test plan

- See the plan. Invariants: Candidate input bytes unchanged; MedXpertQA turn-2 bytes unchanged;
  rows read by the aggregate unchanged; revision ids unchanged; a grader failure keeps the
  Candidate answer; no quoted intent is a label, count or projection.

## Acceptance

- Spec §7.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus: url4 `ErrorCause` (+ `ErrorInfo.cause`), `literal`/
  `literal_value`, `Url4Node.has_data`; engine `benchmarks/case_evaluation.py`,
  `benchmarks/code_calls.py` (shared test support), `FairShareIOLayer` code port, registry
  accepts code mounts; client `literal_value` readers; manual-benchmark guide.
- **Commits:** f6647d5ee spec+plan · 8f4beda25 url4 collected_error · 7f160adf0 engine refactor ·
  ceff22301 test migration · 50a5f3bf6 failure-code cause + design-review fixes.
- **Gates (local):** url4 1930 passed · client 4238 passed · engine 8056 passed with the
  `inspect` extra (2 failures are env-only: they fail identically on origin/main when the
  `inspect` extra is synced, pass without it) · ruff/pyright clean on all three.
  The test-preservation gate needs the owner-approved manifest, written at PR-open.
- **kind validation (prod request cache, 622,779 rows, gemini-3.8-flash, 3 cases):**
  - origin/main baseline: ContractEval F1 0.8 (accuracy 0.6667) · MedXpertQA 0.6667.
  - branch: ContractEval 3/3 cache hits, 0 misses, identical answers/grades/metrics.
    MedXpertQA identical answers/grades/score; first run 3 turn-2 misses — cause is
    PRE-EXISTING (turn 2 embeds the whole turn-1 invocation record incl. accounting, so a
    turn-1 hit vs miss changes turn-2 bytes); proven in-process (byte-identical bodies on both
    checkouts) and on kind: origin/main re-run at the same cache state hit all 6 calls the
    branch filled, and its report differs from the branch's in 0 fields.
  - revision ids of all 84 boards unchanged.
- **Deviations:** answer stays required (no `;optional`: a failed Candidate fails its Case, as
  before); cases data route checks row shape only (count check moved to the aggregate);
  failure codes cross code steps as url4 `cause` (owner decision); MedXpertQA turn-2 prompt
  built by `commit-prompt` code. Follow-up: MedXpertQA turn 2 should embed the turn-1
  OUTPUT, not the record (accounting makes turn-2 bytes depend on turn-1 cache status) —
  changes prompt bytes, so it needs a revision decision.

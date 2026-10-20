---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine, client-sf, url4-sdk
status: in_progress
started: 2026-10-20
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

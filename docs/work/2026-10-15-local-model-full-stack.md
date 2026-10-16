---
ticket: OME-1499
stack: screamingface
status: done
started: 2026-10-15
finished: 2026-10-15
---

# local-model-full-stack — prove discovery through benchmark execution

## Intent

Prove the complete OME-1499 product seam with real AIGateway, local Engine, and SDK processes: a
loopback OpenAI-compatible model server is discovered by `local_provider`, projected into Engine,
snapshotted into an in-process run, used by Fusion members and synthesizer, and scored by MEDXPERT.

## Planned changes

- Add a local-provider E2E backend that starts a deterministic loopback model server and the real
  AIGateway process with an isolated migrated SQLite database.
- Reuse the existing real local Engine process harness and SDK client.
- Add one full-stack Fusion/benchmark test with colon-bearing model ids and raw-wire assertions.

## Test plan

- RED: Engine catalog initially lacks the model without the new local overlay/discovery path.
- Assert AIGateway lists raw `local/*:v1` ids and Engine lists `local/*~v1` routes.
- Run three local members plus local synthesizer against one real MEDXPERT case.
- Assert score, coverage, operation ids, and the exact raw ids received by the model server.
- Assert no off-script endpoint/model request occurs.

## Acceptance

- The test traverses actual AIGateway and Engine HTTP processes plus SDK scheduling/evaluation.
- The result is scored with complete coverage and member/synthesizer evidence.
- The harness performs zero internet egress and leaves no process/database behind.
- Full screamingface package gates pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `packages/screamingface/tests/e2e/harness/local_provider_stack.py` and
  `tests/e2e/test_local_provider_full_stack.py`.
- **Commits:** full-stack review fixes are included in this commit.
- **Gates:** focused full-stack test passed; full `screamingface` gate passed (`ALL GATES GREEN`),
  including 95% coverage, notebook checks, wheel build, and distribution checks.
- **Deviations:** the deterministic upstream is an in-process stdlib HTTP server; AIGateway, Engine,
  SDK planning/scheduling, Fusion execution, and MEDXPERT grading are real subprocess/product paths.
  Backend startup now rolls that server back if sync, migration, or Gateway health startup fails.

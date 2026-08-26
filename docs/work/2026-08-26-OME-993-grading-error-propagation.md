---
ticket: OME-993
stack: screamingface-engine + aigateway + url4 + screamingface (cross-stack, owner-approved single PR)
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-993 — Fix benchmark grading that fails every case while still billing the run

## Intent

A judge-side transport failure (429/5xx or an all-reasoning `length` turn at
`max_tokens=4096`) is collected by url4's default `iterate(on_error="collect")` into an
`{"error": ...}` row, which the case-evaluation route then misreports as
"invalid Criterion envelope" — users get billed runs, zero scores, and a misleading
error. This unit implements all five ticket fixes in one PR (owner-approved scope):

1. Propagate collected-error rows (message/kind/retryability) instead of the envelope
   misdiagnosis.
2. Retry retryable judge failures via url4 `retry=` on the judge sources.
3. AI Gateway: validated `reasoning_effort` for the OpenRouter provider; engine pins the
   judge to `reasoning_effort=low` and raises the judge budget (revision bump).
4. Explicit `on_error` on the engine's benchmark iterates.
5. Cost honesty: grading-stage failures name the engine side and carry retryability.

## Planned changes

- `packages/url4/src/url4/dag/nodes.py` — `_error_payload` additionally carries the
  exception's `code`/`permanent` when present (additive row shape).
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/evaluation.py` —
  `case_evaluation_endpoint` detects `{"error": {...}}` items and re-raises the original
  failure (shared seam: DRACO + HealthBench).
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/draco/exam.py` —
  judge srcs get bounded `retry`; `JUDGE_PARAMS` gains `reasoning_effort=low` and a
  raised `max_tokens`; `criteria` iterate gets explicit `on_error`.
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/` — accept the validated
  `reasoning_effort` standard parameter and map it onto the OpenRouter request body.
- Revision-pin/snapshot fallout: engine definition pin tests, client-side template
  guards, e2e fixtures — updated deliberately with the revision bump.
- `packages/screamingface/tests/e2e/` — new authored failure tapes `judge_token_cap`
  and `judge_429` + scenario tests asserting the propagated (post-fix) failure surface.

## Test plan

- url4: a collected row for an exception carrying code/permanent exposes both; one
  without them keeps today's shape (append-only tests).
- engine (RED first): case-evaluation route fed `[valid_criterion, {"error": ...}]`
  raises the ORIGINAL message, never "invalid Criterion envelope"; aggregate lands it
  as `stage="grading"` with the real cause + retryable flag; HealthBench seam covered.
- engine: built DRACO template carries retry on judge sources and the new judge params;
  revisions move accordingly (pins updated in the same commit).
- aigateway: `reasoning_effort=low` classifies and maps to the OpenRouter body;
  an out-of-enum value fails closed; provider without the param unaffected.
- e2e (opt-in lane): `judge_token_cap` and `judge_429` tapes land as grading failures
  whose message names the real cause.

## Acceptance

- The notebook repro scenario (error row in the criteria array) surfaces the underlying
  judge failure verbatim in the CaseResult; "invalid Criterion envelope" no longer
  reachable from a collected row.
- All five stacks' gates green (`run_gates.py`): url4, screamingface-engine, aigateway,
  screamingface.
- Draft PR open; revision-bump consequences (scoreboard prod seeds, cache-seed
  re-record, golden re-bless) named in the PR body as owner follow-ups.

## Outcome

- **Actual files:** as planned, plus revision-pin fallout the plan anticipated
  generically: `tests/unit/test_benchmark_protocol.py` (2 collected-row shape pins +
  the canonical template sha), `tests/unit/test_draco_3pass_definition.py` (frozen
  revision pin + new judge-resilience pin), `tests/unit/data/
  draco_corrective_loop_candidate.url4`, `apps/scoreboard/tests/fixtures/
  engine_catalog.json`, `benchmarks/draco/definition.py` (invariant text),
  `openrouter_provider/discovery.py` (reviewed evidence),
  `tests/unit/openrouter/test_openrouter_global_cache_keys.py` (key proof),
  `tests/unit/test_benchmark_failure_policy.py` (chain pin).
- **Commits:** ad2aa425 (url4+engine error propagation) · 9f86160f (judge throttle +
  retry + revision move) · f2e0310c (gateway reasoning_effort) · + e2e tapes commit.
- **Gates:** run_gates.py ALL GATES GREEN for url4, screamingface-engine, aigateway,
  screamingface, scoreboard. Gated e2e failure lane run locally: 43 passed
  (FakeGateway + real engine; both new judge-failure scenarios land as stage=grading
  with the original cause).
- **Deviations:**
  - Single PR spans four stacks — owner instruction overriding the cross-cutting
    epic rule.
  - Frozen canonical DRACO revision moved deliberately 66a463248586b277 →
    fe291f4cdc670208 (owner-approved ticket fix #3); prior pins updated in place.
  - Prior tests altered (row-shape pins, revision/template pins, e2e 429 code
    expectation): each is the direct intended consequence of an approved fix and
    documented at the assertion site.
  - judge max_tokens chosen as 8192 (2x pre-incident) alongside reasoning_effort=low;
    both hashed values changed in ONE revision bump per the change-once decision.
  - `_rehearse` gained `tolerate_aborted` (model-less refusals from url4 cancelling
    sibling judge passes mid-request are cancellation artifacts, not improvisation).
- **Owner follow-ups (not in this PR):** deploy aigateway BEFORE the engine (engine
  sends the new param; an old gateway fails it closed); re-seed production scoreboard
  benchmarks at the new revision; re-record judge cache seeds and re-bless goldens
  (paid runs); server-log correlation of the 4 GH #740 run_ids remains open to name
  which trigger fired that day.

---
ticket: OME-993
stack: screamingface-engine + aigateway + url4 + screamingface (cross-stack, owner-approved single PR)
status: in_progress
started: 2026-08-26
finished:
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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:** single PR spans four stacks (owner instruction overriding the
  cross-cutting epic rule); frozen canonical DRACO revision moves (owner-approved via
  ticket fix #3).

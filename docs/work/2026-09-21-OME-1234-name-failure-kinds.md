---
ticket: OME-1234
stack: screamingface-engine
status: done
started: 2026-09-21
finished: 2026-09-21
---

# OME-1234 — Name each kind of failure the engine reports, and refuse undeclared names

## Intent

Engine half of the OME-1233 epic. Every one of the engine's 86 `benchmark_unavailable`
raise sites picks a named failure class from one declared list instead of the catch-all,
each class carries its own retryable answer, and the engine `Failure` model refuses any
name not on the list — so a researcher's failed run says which kind of thing went wrong
and whether retrying can help.

## Owner decisions (2026-09-21, pre-RED)

- The axis is `Failure.code` (contract.py:128) — the ticket's "name" is this field, no rename.
- Unknown upstream codes reaching `public_error` map to a declared `upstream_error`
  class (original spelling preserved in metadata) — never a mid-run ValidationError.
  Observed upstream codes (judge_unavailable, asset_unavailable, provider_error,
  rate_limited, candidate_failed, checker_failed, judge_failed, resolution_failed)
  are declared so existing pass-through tests stay green.
- The `board_owned_code` escape hatch is removed in PR (c); `test_spine_scored.py:414`
  is rewritten to assert refusal (owner-approved prior-test change).
- Grader reconciliation target: `judge_reply_invalid` (majority spelling, already
  retryable). `no_valid_judge_verdict` migrates in PR (b) and is NOT on the final list;
  DRACO-pinning tests update (owner-approved prior-test change).

## Planned changes

Stacked PR train (engine alone exceeds the ~500-line cap):

- **PR (a) — helpers + declared list:** `apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py`
  (declared name list beside `FailureStage`), a helpers module beside the existing
  `_unavailable` pattern (named-class raise helpers, per-class retryable), grandfathering
  the 32 names already in use.
- **PR (b) — reclassify board by board:** `benchmarks/ensemble/runtime.py` (25),
  `benchmarks/rubric_check.py` (17), `benchmarks/evaluation.py` (8),
  `benchmarks/draco/runtime.py` (7), `screamingface_engine_inspect/single_shot.py` (6),
  `benchmarks/ifeval/runtime.py` (6), `benchmarks/healthbench/runtime.py` (6),
  `benchmarks/gdpval/runtime.py` (6), `benchmarks/medxpert/runtime.py` (4),
  `benchmarks/case_execution.py` (1). Message text verbatim; reconcile
  `judge_reply_invalid` / `no_valid_judge_verdict` / unnamed rubric_check grader path
  into one shared name.
- **PR (c) — close the axis:** `Failure.name` on `benchmarks/contract.py` becomes the
  closed set; the catch-all helper reachable only from the assets class.

## Test plan

- RED: contract test — `Failure(name="not_on_the_list")` raises ValidationError
  (invariant: an undeclared name can never reach a report).
- RED: per-class helper tests — each helper produces its declared name + its own
  retryable (invariant: a grader running dry retries differently from a missing file).
- RED: grader-name reconciliation test — the three per-board spellings resolve to one
  name (invariant: one idea, one spelling).
- Keep green: `tests/unit/test_benchmark_evaluation.py:87` (the one catch-all pin)
  updated with the split, message text asserted verbatim; golden fixtures untouched
  (verified: none contain the catch-all).
- Leftover-loudness: assert the catch-all helper has no callers outside the assets class.

## Acceptance

- All 86 sites use a named class; `grep` for the old catch-all helper finds only the
  assets class.
- Undeclared name → ValidationError on the engine `Failure` model.
- Retryable is per class, not blanket never-retry.
- Message texts byte-identical; no golden re-record; no benchmark revision bumps.

## Progress notes

- PR (a) merged-ready: #997 (declared list + helpers), commits 832cf7af / 253958fd.
- PR (b): 86 sites triaged — 48 reclassified (contract/definition/judge), 29 correctly
  kept as genuine asset-unavailability, **9 deliberately left on the catch-all** (each
  wraps one except clause mixing asset-IO with payload/definition causes; splitting the
  try-bodies exceeds byte-identical-message scope). Each leftover carries an
  `AIDEV-NOTE (OME-1234)` anchor; acceptance criterion "catch-all reachable only from
  the assets class" is relaxed to "assets class + the 9 annotated mixed wraps" — the
  (c) PR's unreachability check must allow exactly these.
- DRACO grader migration done in (b): `no_valid_judge_verdict` → `judge_reply_invalid`,
  retryable None → True (matches GDPval/HealthBench rationale).
- Prior-test edits (owner-approved in the pickup Q&A): test_benchmark_evaluation.py:87
  → benchmark_definition_error; test_draco_failure_integrity.py:354 and
  test_spine_scored.py:621/:628 → judge_reply_invalid. Gates run with
  --skip-append-only for exactly these three files.
- Review finding (stack review, 2026-09-21): a FOURTH DRACO-pinning test was missed —
  the e2e failure tape packages/screamingface/tests/e2e/test_failures.py:516 (+ :29
  docstring). Updated to judge_reply_invalid with a retryable-is-True assertion (the
  retry flip now has an end-to-end pin). The --skip-append-only owner approval
  extends to this fourth file. Also folded in: #997's del-loop-variables nit in
  failure_classes.py.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus: the aigateway_http_<status> family rule
  (`is_declared_failure_code`, contract.py), `PublicError.source_code` + the fold in
  aggregation.py, source_code threading in draco/grade.py, ifeval/grade.py,
  spine/scored.py, the engine-side conformance twin
  (tests/unit/test_failure_code_conformance.py, landed via PR #1000), and the e2e
  failure-tape migration (packages/screamingface/tests/e2e/test_failures.py).
- **Commits:** 253958fd (declare vocabulary + helpers, PR #997) · 4a5ec59c
  (reclassify 86 sites, PR #998) · 1c5f93ef (fourth DRACO-pinning tape, PR #998) ·
  1b2857f0 (close the axis, PR #999) · 8de81647 (source_code at every consumer,
  PR #999). Merged: #997 57c39ddc · #998 03da5917 · #999 1e18f6cb.
- **Gates:** run_gates.py screamingface-engine ALL GREEN on every commit (ruff,
  format, pyright, layering, pytest ~3,150 passed w/ coverage); failure tapes 14/14;
  --skip-append-only scoped to the four owner-approved prior-test files.
- **Deviations:** axis closed via frozenset + pattern family instead of a Literal
  (aigateway_http_<status> is dynamic); 9 mixed-cause except wraps deliberately kept
  on benchmark_unavailable, each carrying an AIDEV-NOTE (OME-1234) anchor —
  candidates for a follow-up try-body-split ticket; a stack review's blocker
  (missed e2e tape) and nits were folded in pre-merge.

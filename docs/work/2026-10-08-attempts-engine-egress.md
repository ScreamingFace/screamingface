---
ticket: OME-1458
stack: screamingface-engine
status: done
started: 2026-10-08
finished: 2026-10-08
---

# attempts-engine-egress — Attempt 2 of a Case is never a copy of Attempt 1 (PR 5 of 7)

## Intent

The Engine's egress half of OME-1458 (plan `docs/plan/2026-10-08-OME-1458-attempts-per-case.md`,
PR 5, boxes ④ ⑤). A Candidate Invocation for Attempt 2 or later carries an `attempt` param;
inside it, every model call sends a seed derived from the run's answer seed when that seed
applies, and the Attempt number in the gateway's cache control otherwise (plan P2). Attempt 1,
which is every call of every Benchmark without Attempts, sends exactly what it sent before.
Nothing sends the param yet: the Attempt loop is PR 6.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/case_context.py` — the Attempt
  scope.
- `.../benchmarks/case_request.py` — decode the `attempt` param.
- `.../world/candidate_adapter.py` — strip the param before the policy check, open the scope.
- `.../world/request_parameters.py` — `derive_attempt_seed`, `attempt_egress`.
- `.../world/cache.py` — `attempt_body_field`, `with_cache_policy`.
- `.../world/connector.py` — apply both on every round trip of an Attempt's turn.
- `apps/screamingface-engine/README.md` — the cache-control invariant names the `attempt` key.
- `apps/screamingface-engine/tests/unit/test_attempt_egress.py` — new.

## Test plan

- Decision: Attempt 1 changes nothing; seeded Attempt 2 gets a derived seed and no cache
  Attempt; unseeded Attempt 2 names itself to the cache; a self-seeded call names itself to the
  cache; the derived seed is stable, differs per Attempt and per run seed, and fits 31 bits.
- Cache field: Attempt 1 merges exactly as before; the policy joins an Attempt inside its
  `cache` object, opt-out included (the re-issue path).
- Scope: absent by default; holds its number and closes; Attempt 1 or garbage cannot open one.
- Through the world: Attempt 1 byte-for-byte; unseeded Attempt 2 carries `cache: {"attempt": 2}`
  only; seeded Attempt 2 carries the derived seed; a self-seeded Attempt 2 carries both; an
  opted-out run keeps its opt-out beside the Attempt; a judge call never carries it; a
  malformed param is a contract error; the param is not a retrieval-policy param.

## Acceptance

- Spec acceptance 4 (Engine half): Attempt 2's request always keys differently from Attempt 1's.
- Spec acceptance 1 (egress): every existing Engine unit test passes unmodified.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `case_request.py` (the param decoder lives beside the
  `context_format` decoder).
- **Commits:** see the PR.
- **Gates:** extra-less `pyright` 0 errors; `pytest tests/unit -n auto`: 4632 passed, 44
  skipped.
- **Deviations:** (1) `candidate_call` does not gain an `attempt` argument: PR 6 appends the
  param to the Benchmark's own Candidate Invocation, so no author-facing builder needs it yet.
  (2) The Attempt number rides in the request body from the turn loop, and `_fetch_completion`
  merges the cache policy INTO that `cache` object (`with_cache_policy`), instead of a new
  argument threaded through four call levels: six existing lifecycle-logging tests fake
  `_fetch_completion` with its current signature, and this keeps every one unmodified.

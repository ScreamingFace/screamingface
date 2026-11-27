---
ticket: OME-2013
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-24
finished:
---

# engine-refused-key-403-streak — pin that two undeclared 403 codes extend one refused-key streak

## Intent

Since gateway code provenance (OME-2010, PR #2025, `afe8ec8ea`), the Engine lifts a Gateway
error's `detail.code` only when the Gateway declares it; any other code becomes
`aigateway_http_<status>` (`world/connector.py::_upstream_code`). The refused-key watch (OME-1989,
`world/refused_key_stop.py`) counts a model's 403 Cases per code and restarts the count when the
code changes. So two different undeclared 403 codes, which before #2025 started a new streak each
time they alternated, now both read `aigateway_http_403` and extend one streak: a key refused by a
proxy with varying codes still stops the run after five Cases. The behavior is intended and already
on `main`, but no test pins it. This unit adds that test. No production code changes.

Base: `origin/main` `744f3b89b`. Plan approved by the owner in chat on 2026-11-24.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_refused_key_stop.py`: one new test, appended next to
  `test_a_different_refusal_starts_the_count_over`, using the module's existing harness.
- This ledger; at PR-open, the Linear leaf under `OME-1306` and its `docs/tasks/` mirror.

## Test plan

- New: two undeclared 403 codes alternate over the first five Cases of a solo Candidate. Every
  Case fails `aigateway_http_403`, the Gateway sees exactly five calls, the remaining Cases take
  the Engine's stop code, and the run fails with that code.
- The behavior already exists, so the test cannot be red first. Proof that it bites: with
  `_upstream_code` temporarily lifting any string code (a local mutation, never committed), the
  new test fails and the codes alternate; restored, it passes.
- No prior test changes. The existing `test_a_different_refusal_starts_the_count_over` already
  covers a declared code (`provider_error`) followed by an undeclared one.

## Acceptance

- The new test passes on Python 3.12 and 3.13 and fails under the mutation above.
- `run_gates.py screamingface-engine --base origin/main` all green on Python 3.12 and 3.13, the
  append-only check included.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `apps/screamingface-engine/tests/unit/test_refused_key_stop.py` (one new
  test, `test_two_undeclared_403_codes_extend_one_streak`), this ledger, and the mirror
  `docs/tasks/2026-11-24-OME-2013-engine-refused-key-403-streak.md`. No production code.
- **Commits:** `c773681a4` (the test and this ledger), then the mirror and the ticket backfill,
  on `OME-2013-engine-refused-key-403-streak`. The PR and its merge are recorded at close-out.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` all green on Python 3.13.11
  and 3.12.9: append-only, ruff check, ruff format, pyright, layering, and the full pytest suite
  with coverage at least 80%. The module alone: 25 passed on both. Mutation proof: with
  `and upstream_code in GATEWAY_CODES` removed from `_upstream_code`, the new test fails (the
  Gateway sees 8 calls, not 5, and the codes alternate); restored, it passes.
- **Deviations:** the test sits at the end of the module under its own section header, not next
  to `test_a_different_refusal_starts_the_count_over`. Placed there, the diff aligned the new
  decorator with the next test's and the append-only gate read it as an insertion inside that
  test.

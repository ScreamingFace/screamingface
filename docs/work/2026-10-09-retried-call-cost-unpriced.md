---
ticket: OME-1220
stack: screamingface-engine
status: done
started: 2026-10-09
finished: 2026-10-09
---

# retried-call-cost-unpriced — a call retried after a lost reply reports an unknown cost

## Intent

The Engine connector retries a gateway round trip once after a transport failure. When the
failure happened after the request may have reached the gateway (a lost reply), the lost attempt
may already have been dispatched and billed upstream: OpenRouter bills a cancelled non-streaming
request in full, and the gateway cancels its provider call when the client disconnects, so
nobody on our side learns that attempt's price. Today a retried MISS still reports the second
attempt's price as if it were the whole cost, and a retried HIT is unpriced at the call level but
`"0"` at the operation level. Both understate spend. This unit makes every round trip that
followed an ambiguous failure report an unknown cost, at call, operation and run level, and keeps
the exact cost when the failure provably happened before any byte was sent (connect or pool
phase).

Owner decisions (2026-10-09): D1 unpriced for ambiguous retries, replacing the prior test that
pinned the opposite; D2 connect-phase failures keep the exact price; D3 (a gateway idempotency
key that would remove the double charge) is out of scope and proposed separately.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`:
  `_post_completion` reports whether a retry followed a failure that may have reached the
  gateway (connect/pool-phase failures do not count); `_report_usage` unprices such a miss;
  `_fetch_completion` keeps the flag across the no-cache re-issue.
- `apps/screamingface-engine/src/screamingface_engine/world/accounting.py`:
  `retained_operation_accounting` reports `cost_usd=None` for such a round trip, hit or miss.
- `apps/screamingface-engine/src/screamingface_engine/world/cache_readback.py`: docstring of
  `CacheOutcome.retried` states the narrowed meaning.
- `apps/screamingface-engine/tests/unit/test_ambiguous_retry_pricing.py` (new).
- `apps/screamingface-engine/tests/unit/test_cache_hit_retry_pricing.py`: the owner-approved
  flip of `test_a_retried_miss_keeps_its_provider_authored_price`, pinned in
  `.claude/test-change-approvals/OME-1220.json`.

## Test plan

- Ambiguous failures (`ReadError`, `ReadTimeout`, `RemoteProtocolError`, `WriteError`) then a
  MISS: call cost `None`, operation cost `None`, tokens unchanged.
- Ambiguous failure then a HIT: operation cost `None` (was `"0"`).
- Connect-phase failures (`ConnectError`, `ConnectTimeout`, `PoolTimeout`) then a MISS: exact
  price kept at call and operation level; then a HIT: zero kept.
- No retry: miss priced, hit zero (guards against over-correction).
- Re-issue after a hit refused for age: an ambiguous retry on the first round trip still unprices
  the re-issued response.
- Run level: an unpriced call latches the run UNPRICED (existing behaviour, re-asserted).

## Acceptance

- The result table in the PR body holds and every row is pinned by a test.
- `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` is green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1220.json` (the blob pin
  the append-only gate requires for the owner-approved test flip) and the mirror
  `docs/tasks/2026-10-09-OME-1220-retried-call-cost-unpriced.md`.
- **Commits:** `fix(screamingface-engine): unprice a call retried after a possibly billed failure`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` —
  ALL GATES GREEN (append-only with the OME-1220 approval, ruff check, ruff format, pyright,
  layering, pytest with coverage ≥ 80%): 4708 passed, 86 skipped.
  Mutation checks, each caught: every retry treated as billed (6 tests fail); the re-issue drops
  the first round trip's flag (1); the retained hit stays `"0"` (1); the retained miss keeps its
  price (1). Self-review added direct tests of `_post_completion`'s flag, because the same flag
  also withdraws a hit's saved cost, and a connect-phase retry now keeps that saving.
- **Deviations:** the re-issue path (`_fetch_completion` after a hit refused for age) lost the
  first round trip's retry flag; found during the work and fixed here, with its own test.
  `connector.py` (already over 450 lines) grew by about 20 lines of constant and comments; no
  new responsibility was added to it.

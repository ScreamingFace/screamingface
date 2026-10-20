---
ticket: OME-1687
stack: screamingface-engine
status: done
started: 2026-10-20
finished: 2026-10-20
---

# OME-1687-price-successful-request-only — price a model call from its successful request only

## Intent

The leaderboard shows the cost of intelligence of a model, which assumes each model answers on the
first attempt (owner decision, 2026-10-20). Today a retry makes a call unpriced, and one unpriced
call makes the whole run show "—". This unit removes the OME-1220 rule from the price (engine
transport retry, retried cache hit, its saved cost) and, after OME-1686, prices a gateway-retried
call from the gateway's successful-attempt cost. A successful call with no cost of its own stays
unpriced.

Spec: `docs/spec/2026-10-20-OME-1687-price-successful-request-only.md`.
Plan: `docs/plan/2026-10-20-OME-1687-price-successful-request-only.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`:
  `_report_served_from_cache`, `_report_usage`, `_report_response` (comments),
  `_post_completion` and `_fetch_completion` (comments only).
- `apps/screamingface-engine/src/screamingface_engine/world/accounting.py`:
  `avoided_usd_for_outcome`, `retained_operation_accounting`, `usd_from_aigw` (Phase B),
  comments.
- `apps/screamingface-engine/src/screamingface_engine/world/cache_readback.py`: docstrings only.
- New tests: `tests/unit/test_retry_cost_of_intelligence.py`,
  `tests/unit/test_succeeded_attempt_pricing.py`.
- Approved prior-test flips (spec §8): `test_ambiguous_retry_pricing.py`,
  `test_cache_hit_retry_pricing.py`, `test_cache_saved_cost.py`, `test_signal_accounting.py`
  (comment), with `.claude/test-change-approvals/OME-1687.json`.

## Test plan

- See plan A1 and B1: retried miss and hit priced, retained operation priced, saved cost claimed,
  run total priced, url4 `;retry=` after a 502 locked, capture status still `ambiguous`, gateway
  field rules (reported, unavailable, unit, malformed, `null`, absent key), and the token rule for
  `succeeded_attempt_usage` (mapping, malformed, absent/null).

## Acceptance

- No retry path makes a call, an operation or a run unpriced.
- The price of a call equals the cost of its successful request.
- A successful call with no cost of its own stays unpriced.
- `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` is green.

## Status log

- 2026-10-20: spec and plan written. Waiting for the owner to approve D1–D5 (spec §10) and the
  prior-test changes (spec §8). No code yet.
- 2026-10-20: owner approved D1–D5 and the 6 prior-test flips plus the comment-only edit in
  `test_signal_accounting.py`. D4: keep the flag. Q1 resolved (gateway already stores the
  succeeded send's cost). Q2: no token change, known limitation. Q4: one PR with both phases,
  after OME-1686 merges. Coding starts.
- 2026-10-20: Phase A committed (`b94ff44b1`). Scope change (user): tokens also follow the
  successful attempt, through the gateway key `usage_accounting.succeeded_attempt_usage`
  (absent/null → today's sums; malformed → unknown). Latency stays the all-attempt sum (known
  item). No prior token test changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `world/connector.py`, `world/accounting.py`,
  `world/cache_readback.py` (docstring only); new `tests/unit/test_retry_cost_of_intelligence.py`
  (21 tests) and `tests/unit/test_succeeded_attempt_pricing.py` (28 tests); the approved flips in
  `test_ambiguous_retry_pricing.py`, `test_cache_hit_retry_pricing.py`, `test_cache_saved_cost.py`
  and the comment in `test_signal_accounting.py`, pinned in
  `.claude/test-change-approvals/OME-1687.json`.
- **Commits:** `b94ff44b1` fix(screamingface-engine): stop unpricing a model call after a
  transport retry; Phase B: feat(screamingface-engine): price and count a call from its successful
  attempt.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` — ALL
  GATES GREEN (append-only with 4 approved transitions, ruff check, ruff format, pyright, layering,
  pytest with coverage ≥ 80): 5591 passed, 135 skipped. Phase A gate also green (5563 passed).
- **Deviations:**
  - Scope change mid-unit (user, 2026-10-20): tokens follow the successful attempt through the
    gateway key `usage_accounting.succeeded_attempt_usage`. No prior token test changed (D1
    fallback keeps the all-attempt sum when the key is absent or null).
  - `usd_from_aigw` split into `usd_from_aigw` + `_usd_from_direct_cost_status` (PLR0911); the
    old rule's body is unchanged.
  - `CallAccounting` gained the defaulted field `tokens_from_succeeded_attempt`, so the retained
    operation uses the key's tokens also when the capture is `partial` (key survives degradation).
  - The retained operation's COST still needs a `complete` capture. In the rare degraded case
    (`omitted_attempts > 0`) the live Usage is priced from the key and the retained operation cost
    is `None`. Not changed: no rule covered it; reported to the owner.
  - With a malformed `succeeded_attempt_usage`, the live Usage input/output use the existing
    `_token_count` fallback to the top-level `usage` (the wire has no "unknown" count); cache and
    reasoning are `None`. Never the all-attempt sums.
  - `world/accounting.py` is now ~660 lines (was 593; the 450-line target was already exceeded).
  - Not changed (stale comments in prior tests, outside the approved list): the section header
    above `test_cache_saved_cost.py::test_a_hit_after_a_transport_retry_claims_its_saving` and the
    module docstring of `test_cache_hit_retry_pricing.py` still describe the OME-1220 rule.

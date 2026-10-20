---
ticket: OME-1687
stack: screamingface-engine
status: in_progress
started: 2026-10-20
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

---
id: OME-1923
linear_url: https://linear.app/openmined/issue/OME-1923/read-a-malformed-captured-price-block-with-the-engines-per-number-rule
status: backlog
type: feature
priority: 3
labels: [aigateway, agentic, autonomous]
created: 2026-11-13
closed:
---

# Read a malformed captured price block with the Engine's per-number rule on replay

Mirror of OME-1923 (parent epic OME-1291, E4c).

A follow-up of the PR #1733 review (sergio-bershadsky, round 3, non-blocking finding 2). Not part of #1733.

**Problem.** On a frozen-copy replay, the gateway rebuilds the captured `usage` and `direct_cost` strictly (typed `TokenUsage` / `DirectCost`, `entry_metadata.py` `_captured_reference`) and marks the whole dimension unavailable on any error. The Engine's live read (`world/accounting.py`) reads each number alone. So a malformed block reads differently live and on replay: 10 of 18 single-field corruptions in the review.
- 3 change a budget charge, so a budget Gate can take another branch on replay: a bogus `usage.status` with valid counts; `direct_cost` with `source` missing; `direct_cost.source` not a string.
- 7 change only the tokens_in/tokens_out signals.

Only a corrupted capture, or one from a gateway with another block shape, can hold such a block.

**Fix.** On the gateway side, read the captured block with the Engine's per-number rule (one rule for live and replay).

**Test (from the review).** Add `bogus-usage-status-with-counts`, `cost-source-missing` and `usage-input-malformed` to `_cases()` in `apps/aigateway/tests/unit/test_replay_reference_twin_fixture.py`, regenerate `twins.json`, and check live == replay in `apps/screamingface-engine/tests/unit/test_e4c_replay_price_parity_twin.py`.

Ledger: `docs/work/2026-10-22-e4c-routers-cascades.md` (2026-11-13 review round 3).

---
ticket: OME-1687
spec: ../spec/2026-10-20-OME-1687-price-successful-request-only.md
status: proposed (code starts only after the owner approves the spec decisions D1–D5)
date: 2026-10-20
stack: python (apps/screamingface-engine)
branch: OME-1687-price-successful-request-only
---

# Plan: price a model call from its successful request only

All paths are under `apps/screamingface-engine/` unless they start with `docs/` or `.claude/`.
Each unit is one commit. Tests are append-only (`run_gates.py`). A prior test changes only through
the owner-approved manifest `.claude/test-change-approvals/OME-1687.json` (spec §8). Gate:
`uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` (from the repo
root).

Phase A does not need the gateway. Phase B needs the OME-1686 field, but it is safe with an older
gateway (spec D1), so it can merge before OME-1686 is deployed.

## Phase A — retries no longer unprice a call (engine only)

### A1 — RED: the new rule, in a new test file

New file `tests/unit/test_retry_cost_of_intelligence.py`. Reuse the harness shape of
`tests/unit/test_ambiguous_retry_pricing.py` (`httpx.MockTransport`, `_no_backoff`, a recording
usage sink). Do not import private helpers from that test module; copy the small builders.

1. `ReadError` / `ReadTimeout` / `RemoteProtocolError` / `WriteError` (parametrized), then a miss
   with cost 0.001 → Usage `cost_usd == Decimal("0.001")`.
2. The same, then a hit → Usage `cost_usd == Decimal("0")`.
3. The same miss → `retained_operation_accounting(..., cache=<retried miss>)` → `"0.001"`;
   retried hit → `"0"`.
4. A retried hit with a reported reference → `avoided_usd_for_outcome` returns the reference
   saving; `RunCacheCounters` puts it in `saved_cost_usd`, `unpriced_hits == 0`.
5. Run level: `_RunState` with one retried call (0.001) and one normal call (0.004) →
   `pricing_version == PRICING_VERSION`, `total_usd == Decimal("0.005")`.
6. P3 lock: a 502 response → `ResolutionError`, `permanent is False`, no Usage event. A second
   round trip with cost 0.001 → one Usage event, priced 0.001.
7. Capture guard: after a lost reply, `_CaptureProbe.status()` is still `"ambiguous"`.

Run the file. Expect 1–4 to fail with the OME-1220 values (`None`, empty saving). Expect 5–7 to
pass already (they lock behaviour that must not change). Record this in the ledger.

### A2 — GREEN: remove the retry condition from the price

- `src/screamingface_engine/world/connector.py`
  - `_report_served_from_cache` (`:674`): remove the `retried` keyword; `cost_usd=_hit_cost(call)`.
  - `_report_usage` (`:757-758`): call `_report_served_from_cache(model, call)`.
  - `_report_usage` (`:778-781`): `cost_usd=None if call is None else call.cost_usd`.
- `src/screamingface_engine/world/accounting.py`
  - `avoided_usd_for_outcome` (`:306-320`): return `avoided_usd_from_aigw(aigw)`. Keep the
    `cache` parameter (the connector seam and its tests call it).
  - `retained_operation_accounting` (`:472`): `cost_usd="0"`; (`:508-512`): remove
    `and not cache.retried`.
- Keep `possibly_billed`, `CacheOutcome.retried` and `_CaptureProbe` (spec D4).

Run the new file and every prior test. Expect exactly the 6 prior test functions of spec §8 to
fail. Nothing else may fail.

### A3 — the approved prior-test flips (only after D5)

- Apply the edits of spec §8 to `tests/unit/test_ambiguous_retry_pricing.py`,
  `tests/unit/test_cache_hit_retry_pricing.py`, `tests/unit/test_cache_saved_cost.py`, and the
  comment in `tests/unit/test_signal_accounting.py`.
- Write `.claude/test-change-approvals/OME-1687.json` (issue, branch, approver, date, scope,
  reason, and `base_blob` / `approved_blob` for each file, as in `OME-1220.json`).

### A4 — comments

Update every comment in spec §6 that belongs to Phase A. Anchor the new rule with
`FEATURE: cost of intelligence (OME-1687)` and `INVARIANT:` lines. Do not add a comment that only
restates the code.

### A5 — gate and commit

`run_gates.py screamingface-engine --base origin/main` green. Commit:
`fix(screamingface-engine): stop unpricing a model call after a transport retry`.

## Phase B — price from the gateway's successful-attempt cost

### B1 — RED

New file `tests/unit/test_succeeded_attempt_pricing.py`, with the cases of spec §9 Phase B. Build
the `_aigw` envelopes inline (the shape of `tests/unit/test_accounting.py`'s builders). Include the
connector-level case: one response whose `attempts[]` holds a 503 (`unavailable`) and a 200
(`reported` 0.00042), `direct_cost_status: "partial"`, and the new field.

Expect: the `partial` + field cases fail (`None` today). The absent-key and `null` cases pass
already (they lock D1).

### B2 — GREEN

`src/screamingface_engine/world/accounting.py`:
- Add the constant `_SUCCEEDED_ATTEMPT_DIRECT_COST = "succeeded_attempt_direct_cost"` beside the
  module constants.
- Add `_succeeded_attempt_usd(direct_cost: Mapping[str, Any]) -> Decimal | None`: `status` must be
  `"reported"`, then `_credits_to_usd([{"unit": ..., "amount": ...}])`. Reuse the converter; do not
  add a second precision context.
- In `usd_from_aigw` (`:187`), after the `economics` check: if the key is present and the value is
  a mapping → return `_succeeded_attempt_usd(...)`; if present, not `None` and not a mapping →
  `None`; else the current code, unchanged.
- Update the docstring and the AIDEV-NOTE (`:187-200`): the producer now gives the successful
  attempt's cost directly; still never walk `attempts[]`.

Run all tests. No prior test may fail in this phase.

### B3 — gate and commit

`run_gates.py screamingface-engine --base origin/main` green. Commit:
`feat(screamingface-engine): price a call from the gateway's successful-attempt cost`.

## Verification after both phases

- Spec §2 table: P1 and P2 are priced; P3 is unchanged and locked by A1.6.
- No live provider call and no full eval (stub transport only).
- Optional, owner-run: a local stack (`~/sf-local`) with an OME-1686 gateway, where a stub
  provider returns 503 then 200, shows a priced run.

## Out of scope

The false zero in `runner/executor.py:692` / `:1193`, token counts of failed attempts, and the
retry rules themselves (spec §7).

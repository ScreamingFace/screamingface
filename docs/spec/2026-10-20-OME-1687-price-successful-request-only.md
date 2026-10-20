---
ticket: OME-1687
status: approved 2026-10-20 (D1–D5 as recommended; Q1–Q4 resolved in §11)
date: 2026-10-20
related: OME-1686 (gateway field, blocks Phase B), OME-1220 (the rule this spec reverses), OME-849 (run cost), OME-1287 (parent epic), OME-1519 (canceled)
---

# Price a model call from its successful request only

All paths are under `apps/screamingface-engine/src/screamingface_engine/` unless they start with
`tests/`, `docs/` or `.claude/`. Tests are under `apps/screamingface-engine/`.

## 1. Product rule (owner decision, 2026-10-20)

The leaderboard shows the **cost of intelligence** of a model. It does not show the money that
one run spent. The cost of intelligence assumes a perfect world: each model answers on the first
attempt, in a consistent way. A retry is an infrastructure event. Thus:

- **R1.** The price of a model call is the cost of its **successful** request only.
- **R2.** A retry never makes a call, an operation or a run unpriced.
- **R3.** A successful call whose own cost is unknown (no `usage.cost`, an unknown unit, an
  unpriced model) stays unpriced. This is a real unknown, not a retry effect.
- **R4.** One unpriced call still makes the run unpriced (`runner/executor.py:504-505`, `:684`).
  This spec does not change that rule.
- **R5.** A judge redraw (a reply that cannot be parsed) is a successful call. Its cost
  continues to count.
- **R6 (scope change, user decision 2026-10-20).** Token counts follow the same rule: they come
  only from the successful attempt, never from failed attempts. Cost and tokens follow one rule:
  the engine never calculates them from `attempts[]`.

This rule reverses OME-1220 (owner decision D1 of 2026-10-09, "unknown over a confident
undercount"). That decision protected the actual spend. The new rule protects the model price.

## 2. Today: three retry paths make a call unpriced

| # | Path | Where | Effect today |
|---|---|---|---|
| P1 | Engine transport retry after an ambiguous failure (`ReadError`, `ReadTimeout`, `RemoteProtocolError`, `WriteError`) | `world/connector.py:806-827` sets `possibly_billed`; `:1038-1070` carries it into `CacheOutcome.retried` | Miss: `_report_usage` sets `cost_usd=None` (`:778-781`). Hit: `_report_served_from_cache` sets `None` (`:722`). Retained operation: `None` (`world/accounting.py:472`, `:511`). Saved cost withdrawn (`world/accounting.py:319`) and counted in `unpriced_hits` (`runner/cache_counters.py:241-253`). |
| P2 | Gateway retry inside one HTTP call (429, 503, 529; `apps/aigateway/src/aigateway/core/retry.py:23`) | `world/accounting.py:206-213` | The failed attempt has `direct_cost.status = "unavailable"`, so the gateway reports `direct_cost_status = "partial"`. `usd_from_aigw` accepts only `complete` and returns `None`. |
| P3 | url4 `;retry=` or judge retry after a 5xx (`world/connector.py:1642` marks 429/5xx `permanent=False`; `screamingface_engine_inspect/judge_redraw.py:73-80`) | — | **Already correct.** `_raise_for_status` raises before any accounting is read (`world/connector.py:1052`, `:1067`), so the failed response emits no Usage. The next call is priced from its own `_aigw`. |

A connect-phase failure (`_NEVER_SENT`, `world/connector.py:147`) already keeps the exact price.

## 3. Every use of the retry flag, classified

| Site | Use | Class | Action |
|---|---|---|---|
| `world/connector.py:806-827` `_post_completion` → `possibly_billed` | Computes the flag | Fact | Keep (D4). Update the docstring (`:795-802`): the flag no longer changes a price. |
| `world/connector.py:1038-1070` `_fetch_completion` | Carries the flag across the `max-age` re-issue into `read_cache_outcome` | Fact plumbing | Keep (D4). Update the INVARIANT at `:1068-1069`. |
| `world/cache_readback.py:110-151` `CacheOutcome.retried`, `read_cache_outcome(retried=)` | Holds the flag | Fact | Keep (D4). Rewrite the docstring (`:111-124`, `:132-133`). |
| `world/connector.py:722` `_report_served_from_cache` | `cost_usd=None if retried` | **PRICING** | Change: a retried hit is priced by `_hit_cost(call)`, like any hit. Remove the `retried` keyword. |
| `world/connector.py:757-758` `_report_usage` hit branch | Passes `retried=cache.retried` | **PRICING** | Change with the row above. |
| `world/connector.py:778-781` `_report_usage` miss branch | `None if cache.retried` | **PRICING** | Change: `cost_usd = None if call is None else call.cost_usd`. |
| `world/connector.py:651` `_report_response` → `avoided_usd_for_outcome` | Saved cost of a hit | **PRICING** (saved cost) | Change (D2): a retried hit claims its saving. |
| `world/accounting.py:306-320` `avoided_usd_for_outcome` | Withdraws the saving when `cache.retried` | **PRICING** (saved cost) | Change (D2): return `avoided_usd_from_aigw(aigw)` for every outcome. Keep the function as the one seam the connector calls. |
| `world/accounting.py:472` `retained_operation_accounting` hit | `None if cache.retried else "0"` | **PRICING** | Change: `"0"`. |
| `world/accounting.py:508-512` `retained_operation_accounting` miss | `... and not cache.retried` | **PRICING** | Change: remove the condition. |
| `world/accounting.py:578-580` `signal_accounting_from_aigw` | Ignores `retried` already | — | No change. Update the WHY text, which cites the withdrawal. |
| `runner/cache_counters.py:241-253` | Counts a hit with no saved price as `unpriced_hits` | — | No code change. A retried hit stops being an unpriced hit through `avoided_usd_for_outcome`. |
| `world/connector.py:1078-1104` `_CaptureProbe.retried` / `lost_reply`, `:1163` | Frozen-copy capture ordering | **REPLAY / CAPTURE SAFETY** | **Do not change.** It is a separate field. It is set for every lost reply, connect phase included. |
| `world/connector.py:1192` `_fetch_replay` | Discards the flag (`_retried`) | Replay | No change. |
| `world/connector.py:121-124` `_REPLAYED` | A replay is an unretried hit | Replay | No change. |

**The cache revalidation path** (`world/connector.py:1055-1070`, re-issue with `use-cache: false`)
is not affected. It decides on `requires_revalidation(cache, outcome)`
(`world/cache_readback.py:155`), which does not read `retried`. The discarded hit is still never
reported (`:1027-1029`). Only the INVARIANT comment at `:1068-1069` changes.

## 4. Gateway contract (OME-1686, fixed)

- New key `_aigw.request_economics.succeeded_attempt_direct_cost`. Its value is the JSON of the
  successful attempt's `direct_cost` (the shape of `usage_accounting.attempts[].direct_cost`:
  `status`, `amount`, `unit`, `source`, …), or `null` when no attempt succeeded (cache hit,
  failure, not dispatched).
- The gateway calculates it from all attempts. It does not depend on truncation or on
  `capture_status`.
- New key `_aigw.usage_accounting.succeeded_attempt_usage` (added 2026-10-20 for R6). Its value
  is the `usage` of the same successful record, with the shape of `attempts[].usage`
  (`input.total`, `input.cache_read`, `input.cache_write`, `output.total`, `output.reasoning`), or
  `null`. The gateway calculates it from all records. It survives truncation and the size
  degradation (`_degrade_to_bound`).
- `direct_cost_status`, `known_direct_cost_subtotals` and `attempts[]` do not change.

## 5. Engine pricing rule (Phase B, `world/accounting.py` `usd_from_aigw`)

In this order. The function stays total and never raises (`:192-195`).

1. No `_aigw` mapping, or no `request_economics` mapping → `None` (today).
2. The key `succeeded_attempt_direct_cost` is **present and a mapping** → price from it:
   - `status == "reported"` and `unit == "openrouter_credits"` and a canonical `amount` →
     `_credits_to_usd([{"unit": unit, "amount": amount}])` (the same 1:1 converter and precision
     context as today, `:161-185`).
   - Any other status, unit or amount → `None` (R3).
3. The key is **present and not a mapping and not `null`** (malformed) → `None`.
4. The key is **absent or `null`** → today's rule, unchanged: `complete` → the single subtotal;
   `not_applicable` and a cache hit → `Decimal(0)`; otherwise `None` (`:206-213`).

**Why the field wins over `direct_cost_status` (step 2 before step 4):** the field answers the
question R1 asks. For a call with one attempt the two give the same number.

**Fallback when the key is absent (D1, recommended: step 4 = today's rule).** The key is absent
for an older gateway, for a frozen copy captured before OME-1686, and for a response the gateway
cache stored before OME-1686. Today's rule gives the same result as now for these responses. A
call with no retry is `complete`, so it is priced. Only a gateway-retried call from an older
gateway stays unpriced, and that stops when OME-1686 is deployed. The alternative, to take the
last `succeeded` entry of `attempts[]`, is rejected: `usd_from_aigw`'s AIDEV-NOTE (`:197-200`)
forbids money from `attempts[]`, and `attempts[]` can be truncated (`omitted_attempts`).

`null` follows the same fallback because a cache hit sends `null`, and step 4 is what prices a
hit at exactly 0 (`:209-213`).

**`PRICING_VERSION` (D3, recommended: no change).** `"openrouter-credits-1usd"` names the
conversion method (`:57-60`): OpenRouter credits to USD at 1:1. That method does not change. Only
the choice of attempt changes, and for a call with no retry the number is the same. No consumer
outside the engine reads the string (a repository search finds it only at `world/accounting.py:60`;
the SDK compares only with `"unpriced"`). A new version would split priced runs on the board by an
infrastructure event.

**Token rule (R6, mirror of D1; `read_aigw`, live Usage, retained operation).**

1. `succeeded_attempt_usage` is a mapping → take all 5 token classes from it. The retained
   operation uses these tokens also when the capture is not `complete`, because the key survives
   truncation and degradation.
2. The key is present, not a mapping and not `null` (malformed) → the 5 classes are unknown
   (`None`). Never mix them with the all-attempt sums. The live Usage then uses its existing
   fallback for input and output (the top-level `usage`, `world/connector.py` `_token_count`).
3. The key is absent or `null` → today's behaviour, unchanged: the sum over every attempt.

Because of rule 3, prior token tests (their fixtures have no key) do not change.

## 6. Comments that state the old rule (update them)

- `world/connector.py:674-713` `_report_served_from_cache` docstring: the INVARIANT "a RETRIED hit
  is `None`" and the AIDEV-NOTE (OME-1220).
- `world/connector.py:642-645` `_report_response` INVARIANT "a hit whose round trip was RETRIED is
  never priced".
- `world/connector.py:778-780` `_report_usage` INVARIANT (OME-1220).
- `world/connector.py:795-802` `_post_completion` docstring.
- `world/connector.py:1068-1069` `_fetch_completion` INVARIANT (OME-1220).
- `world/cache_readback.py:111-124` `CacheOutcome.retried` and `:132-133`.
- `world/accounting.py:306-318` `avoided_usd_for_outcome`; `:470-471` and `:508-509`
  (OME-1220 INVARIANTs); `:578-580` (WHY); `:187-200` `usd_from_aigw` docstring (Phase B).
- Each new or changed comment states the R1 rule with `FEATURE: cost of intelligence (OME-1687)`.

## 7. Out of scope (separate findings)

- **False zero.** An unpriced run publishes `CostBreakdown(total_usd=total or Decimal("0"))`
  (`runner/executor.py:692`), and `RunSummary.cost_usd` copies it (`:1193`). This contradicts
  `runner/summary.py:7-8` ("never a false zero"). The prior test
  `tests/unit/test_cache_hit_retry_pricing.py::test_a_retried_hit_makes_the_whole_run_total_unpriced`
  pins this zero. Only `pricing_version = "unpriced"` shows the truth. Not changed here.
- **Retained cost after degradation (owner decision A, 2026-10-20).** When the gateway sent
  `succeeded_attempt_direct_cost`, the retained operation's cost follows it like the live Usage,
  also when the capture is `partial` or `omitted_attempts > 0`. Without the key, the retained cost
  keeps today's rule (it needs a `complete` capture).
- **Cache hit first.** A cache hit is never priced from `succeeded_attempt_direct_cost`, even when
  a hit carries a mapping there: `usd_from_aigw` checks for a hit before it reads the key.
- **Known item: latency.** `provider_latency_ms` continues to add the latency of every attempt,
  failures included (`world/accounting.py` `read_aigw`). User decision 2026-10-20: out of scope.
- **Known item: older gateways.** With no `succeeded_attempt_usage` key, tokens are the sum over
  every attempt (rule 3 above). A failed gateway attempt with no usage makes that sum `None`
  (`accumulate`); the live Usage then falls back to the top-level `usage` for input and output.
- The engine retry rules (when to retry). Only the price changes.
- Gateway changes. They are in OME-1686.

## 8. Prior tests that change (owner approval required)

The append-only gate needs an approval manifest `.claude/test-change-approvals/OME-1687.json`
(the format of `OME-1220.json`). Each change below flips an assertion that encodes the OME-1220
rule. No other prior test changes.

`tests/unit/test_ambiguous_retry_pricing.py`
- `test_a_miss_retried_after_a_possibly_billed_failure_is_unpriced` (`:165`): expect
  `Decimal("0.001")`, not `None`. Rename to `..._keeps_its_exact_price`.
- `test_a_possibly_billed_retry_is_unpriced_in_the_retained_operation` (`:299`): expect `"0.001"`
  (miss) and `"0"` (hit), not `None`. Rename to `..._keeps_its_price_in_the_retained_operation`.
- Module docstring (`:1-21`): state the R1 rule instead of the OME-1220 rule.

`tests/unit/test_cache_hit_retry_pricing.py`
- `test_a_hit_after_a_retry_reports_an_unknown_price_not_a_zero_one` (`:163`): expect
  `Decimal("0")`. Rename to `test_a_hit_after_a_retry_is_priced_at_zero`.
- `test_a_retried_miss_is_unpriced_too` (`:198`): expect the provider-authored price. Rename to
  `test_a_retried_miss_keeps_its_price`.

`tests/unit/test_cache_saved_cost.py`
- `test_a_hit_after_a_transport_retry_is_not_priced` (`:296`): expect the reference saving
  (`AvoidedCost(usd=..., provenance="reported")`). Rename to `..._claims_its_saving`.
- `test_a_withdrawn_price_lands_in_the_unpriced_bucket_and_no_total` (`:335`): with a retried hit,
  expect `unpriced_hits == 0` and the saving in `saved_cost_usd`. Rename to
  `test_a_retried_hit_saving_lands_in_the_priced_total`.

`tests/unit/test_signal_accounting.py::test_a_retried_hit_still_gives_the_reference_numbers`
(`:121`): the comment at `:122` cites the withdrawal. Comment only; the assertions stay.

These prior tests **stay unchanged** and pass under the new rule (they assert tokens, the flag,
or the connect-phase price): `test_ambiguous_retry_pricing.py` `:175`, `:184`, `:195`, `:204`,
`:235`, `:245`, `:250`, `:258`, `:317`, `:330`; `test_cache_hit_retry_pricing.py` `:172`, `:183`,
`:210`, `:229`; `test_cache_saved_cost.py:318`; `test_cache_readback.py:649`;
`test_model_call_lifecycle_logging.py:202`, `:220`; all of `test_accounting.py` (their envelopes
have no `succeeded_attempt_direct_cost` key, so step 4 applies).

## 9. New tests

Phase A (`tests/unit/test_retry_cost_of_intelligence.py`, new):
- An ambiguous transport retry, then a miss: the Usage has the price of the answering response,
  and the retained operation has the same price.
- An ambiguous transport retry, then a hit: the price is `Decimal("0")` and the saved cost is the
  reference saving.
- A run with one retried call and one normal call is priced, and its total is the sum.
- The url4 `;retry=` lock (P3): a 502 response raises a `ResolutionError` with
  `permanent=False` and emits no Usage. The next round trip is priced on its own. The run total is
  the second call's price.
- The frozen-copy capture status after a lost reply is still `ambiguous` (guards the
  REPLAY/CAPTURE row in §3).

Phase B (`tests/unit/test_succeeded_attempt_pricing.py`, new):
- `partial` economics with the field `reported` 0.00042 credits → `Decimal("0.00042")`.
- The field wins over a disagreeing `complete` subtotal.
- The field `unavailable`, `invalid`, or with a unit other than credits, or a non-canonical
  amount → `None`.
- The field malformed (a string, a list, a number) → `None`; never raises.
- The field `null` and a cache hit with `not_applicable` → `Decimal(0)`.
- The field `null` and no hit → today's rule.
- The key absent → today's rule (`complete` priced, `partial` unpriced).
- Connector level: a gateway response with attempts 503 + 200 and the field → the Usage price is
  0.00042, the retained operation is `"0.00042"`, and the run is priced.
- Tokens: `succeeded_attempt_usage` a mapping → all 5 classes from it (not the sum), in
  `read_aigw`, the live Usage and the retained operation (also with a `partial` capture);
  malformed → `None` for the 5 classes (live input/output fall back to the top-level `usage`);
  absent or `null` → the all-attempt sum.

## 10. Owner decisions (approved 2026-10-20)

- **D1.** When the key is absent or `null`, use today's rule (§5 step 4). Recommended.
- **D2.** A retried cache hit claims its saving (`avoided_usd_for_outcome` stops the withdrawal).
  Recommended: the leaderboard reproduction cost is spend plus saving
  (`apps/scoreboard/src/scoreboard/scores/reproduction_cost.py:40`), and in a perfect world the hit
  replaces the original call, whose cost is the reference.
- **D3.** Keep `PRICING_VERSION = "openrouter-credits-1usd"`. Recommended.
- **D4.** Keep the `possibly_billed` / `CacheOutcome.retried` flag as a fact that no price reads.
  Recommended for this unit: removing it changes 12 more prior tests
  (`test_ambiguous_retry_pricing.py:235`, `:245`, `:250`, `:258`, `:299`, `:317`, `:330`;
  `test_cache_readback.py:649`; `test_model_call_lifecycle_logging.py:202`, `:220`;
  `test_signal_accounting.py:121`, `:131`) for no product effect. Alternative: delete the flag and
  those tests' flag assertions in a follow-up.
- **D5.** Approve the prior-test changes in §8.

## 11. Resolved questions (owner, 2026-10-20)

- **Q1.** Already true. The gateway cache row stores the cost of the last succeeded send
  (`apps/aigateway/src/aigateway/plugins/taxonomy/entry_metadata.py:184-213`). It is certified
  when the collector status is `complete`, which is the case after a 503 → 200 retry. No
  dependency on OME-1686.
- **Q2.** Superseded by the scope change R6 (user decision 2026-10-20): tokens follow the
  successful attempt through the gateway key `usage_accounting.succeeded_attempt_usage`. The
  engine-only proposal (terminal attempt of `attempts[]`) was rejected. Latency stays out of
  scope.
- **Q3.** Keep the flag (D4).
- **Q4.** One PR with both phases. It opens after the OME-1686 PR merges. Phase B codes against
  the fixed contract (§4), with test fixtures that hold the key, and with the fallback (D1) when
  the key is absent.

---
ticket: OME-1738 (under OME-1287)
status: approved 2026-10-26 (user: "write the spec with the $0 rule, then implement it")
date: 2026-10-26
related: OME-1287 (cost epic), OME-1446 (zero-completion insurance, the precedent), OME-1687 (price the successful request only), OME-849 (run cost)
---

# Price an OpenRouter refusal before output as $0

Paths start at `apps/aigateway/src/aigateway/` (gateway) or
`apps/screamingface-engine/src/screamingface_engine/` (engine) unless they start with `docs/`.

## 1. Problem

On the lab_bench boards, 7 rows show cost "—". Each row contains `claude-opus-5.5` (solo, or in a
trio). Anthropic refuses some biology questions **before** the model writes output.

The gateway records that call as `direct_cost.status = "unavailable"`. The engine then marks the
call unpriced (OME-1687 R3), and one unpriced call makes the run unpriced (R4). A later replay
that hits the cache for the same call is an unpriced hit, so a trio becomes `partial`.

## 2. Evidence

### 2.1 Live call (2026-10-26, n=1)

LitQA2 row 0, `anthropic/claude-opus-5.5` through OpenRouter, `max_tokens 128000`, reasoning
effort high. HTTP 200 in 2.3 s. Full body:

```json
{"id": "gen-1793053597-ybUQmEyCYvKGZ0aEDweM", "object": "chat.completion",
 "created": 1793053597, "model": "anthropic/claude-opus-5.5",
 "provider": "Claude Platform on AWS", "system_fingerprint": null, "service_tier": null,
 "choices": [{"index": 0, "logprobs": null, "finish_reason": "content_filter",
              "native_finish_reason": "refusal",
              "message": {"role": "assistant", "content": null, "refusal": null,
                          "reasoning": null}}]}
```

- There is **no `usage` key**.
- `GET /api/v1/generation?id=<id>` gives 404 "not found", also 3 minutes later.
- A control call ("Reply with the single word: ok") had `usage.cost 0.000152`, and its generation
  record was found in 20 s with `total_cost 0.000152`.

Thus OpenRouter keeps no billing record for this refusal. The cost through OpenRouter is $0.

### 2.2 Anthropic documentation

A refusal is HTTP 200 with `stop_reason: "refusal"`. Anthropic bills some refusals before output
(categories bio, frontier_llm, reasoning_extraction) when the call goes direct. We do not call
Anthropic direct. We pay OpenRouter, and OpenRouter shows no charge. The money that we pay is the
money that this spec records.

### 2.3 Mid-stream refusals are different

The 2026-10-19 prod cache export has 112 `content_filter` rows (62 `fable-5.1`, 50 `opus-5.5`).
All of them have reasoning output and a `usage.cost`, and all are priced. This spec does not
change them.

## 3. Rule

**P1.** The gateway certifies `DirectCost.provider_guaranteed_zero(unit="openrouter_credits",
source="openrouter.pre_output_refusal")` for one OpenRouter attempt only when **all** of these are
true:

1. The attempt succeeded and its HTTP status is 200.
2. The base mapper gave `direct_cost.status == "unavailable"` (a reported cost always wins).
3. The request has no potential auxiliary charge (`has_potential_auxiliary_charge` is `False`:
   no plugins, no `openrouter:*` tools, no file parts).
4. The raw body has only known top-level fields, and `usage` is absent or `null`.
5. `choices` is a list with exactly one mapping. Its `finish_reason` is `"content_filter"` and its
   `native_finish_reason` is `"refusal"`.
6. The message has no output: `content`, `reasoning`, `refusal` are absent, `null` or `""`;
   `tool_calls`, `reasoning_details` are absent, `null` or `[]`.

If one condition is false, the evidence does not change (fail closed).

**P2.** Token usage stays as the base mapper gives it. The gateway does not invent zero tokens.

**P3.** The engine prices a successful attempt with `provider_guaranteed_zero`, unit
`openrouter_credits`, amount `"0"` and source `openrouter.pre_output_refusal` as `Decimal(0)`.

**P4.** The engine prices a cache reference with the same direct cost as a saved cost of
`Decimal(0)` with provenance `reported`. The hit is a priced hit, not an unpriced hit.

**P5.** A `provider_guaranteed_zero` from any other source on a successful attempt stays
unpriced. This keeps OME-1687 R3 for zero rules that the engine does not know.

## 4. Why this is correct (and not too wide)

- The rule follows the money that we pay. OpenRouter has no generation record, so there is no
  charge to find later.
- The rule is narrow. It needs the exact native signal (`refusal`) and no output of any kind. A
  refusal with reasoning, content or tool calls, or with a `usage` object, stays as today.
- It uses the existing status `provider_guaranteed_zero`, which the schema, the collector, the
  renderer and the cache-entry metadata already support (OME-1446). No schema change.
- The status already survives into the cache-entry metadata (`cache_entry_metadata_from_session`
  copies `direct_cost` from the last succeeded record), so a hit gets it with no extra code.

## 5. Changes

| Area | File | Change |
|---|---|---|
| Gateway | `plugins/openrouter_provider/pre_output_refusal.py` (new) | `proves_pre_output_refusal(raw_response, *, http_status, request_has_potential_auxiliary_charge) -> bool` (conditions 1, 3–6) |
| Gateway | `plugins/openrouter_provider/usage_accounting.py` | `PRE_OUTPUT_REFUSAL_SOURCE`; `supplement_openrouter_usage_accounting` also certifies P1 when `failed` is false |
| Engine | `world/accounting.py` | `_is_priced_zero(direct_cost)`; used by `_succeeded_attempt_usd` (P3) and `avoided_usd_from_aigw` (P4) |

## 6. Limits and follow-ups

- **L1.** Cache rows that prod wrote before this change keep `direct_cost: unavailable` in their
  metadata. A replay that hits such a row stays an unpriced hit until the row is written again.
  The existing lab_bench rows on the board do not change. A new run (or a repair of the stored
  metadata) is necessary. Follow-up, not in this unit.
- **L2.** The rule is OpenRouter only. A direct Anthropic provider would need its own rule,
  because Anthropic bills some refusals before output (§2.2).
- **L3.** Evidence is one live call. If OpenRouter starts to bill such refusals, it will send a
  `usage.cost`, and condition 4 then keeps the reported price.

## 7. Tests

- Gateway (`tests/unit/usage_accounting/test_openrouter_pre_output_refusal.py`): the §2.1 body is
  certified; tokens stay unavailable; the rendered metadata is schema valid and carries the zero
  in `succeeded_attempt_direct_cost`; the cache-entry metadata keeps it; each failed condition of
  P1 keeps `unavailable`.
- Engine (`tests/unit/test_pre_output_refusal_pricing.py`): P3, P4, P5; the prior test
  `test_a_successful_attempt_without_a_reported_credit_price_is_unpriced[guaranteed_zero]` stays
  unchanged and green.

## 8. Amendment 2026-10-27: check billing facts, not the reply format

The gateway sends `X-OpenRouter-Metadata: enabled` on every OpenRouter call
(`openrouter_provider/plugin.py` `_TRUSTED_ATTRIBUTION`). A live refusal on 2026-10-27 with that
header had one more top-level field (it also had no generation record, 2 of 2 refusals):

```json
"openrouter_metadata": {"requested": "anthropic/claude-opus-5.5", "strategy": "direct",
  "region": "EZE", "summary": "available=5, selected=Claude Platform on AWS", "attempt": 1,
  "is_byok": false, "endpoints": {"total": 11, "available": [{"provider": "...",
  "model": "...", "selected": true}, "..."]}, "generation_time": 2479}
```

P1 condition 4 accepted only known top-level fields, so it rejected that field and the rule never
applied in prod. The owner decision (2026-10-27): the proof checks only the facts that tell if
OpenRouter billed the call. The format of the reply (which fields exist, the types of fields that
carry no money) does not change the result. A cost stays unknown only in rare cases.

P1 is replaced by:

**P1'.** The gateway certifies the zero for one OpenRouter attempt when all of these are true:

1. The attempt succeeded and its HTTP status is 200.
2. The base mapper gave `direct_cost.status == "unavailable"` (a reported cost always wins).
3. The request has no potential auxiliary charge (no plugins, no `openrouter:*` tools, no file
   parts). This is a fact about our request, not about the reply.
4. The reply has no `usage` (absent or `null`), and no `error`. When OpenRouter bills a call, it
   sends `usage` with the cost.
5. `choices` is a list with exactly one choice. Its `finish_reason` is `"content_filter"` and its
   `native_finish_reason` is `"refusal"`.
6. The message has no output: `content`, `reasoning` and `refusal` are absent, `null` or `""`, and
   `tool_calls` and `reasoning_details` are absent, `null` or `[]`.

7. No money field anywhere in the reply holds a non-zero value: a value under any key that
   contains `cost` or `amount` (for example a pipeline `cost_usd`) is absent, `null` or zero. A
   value that is not a number (for example `"0.25"`) is not a zero.

All other fields are ignored, in the body, the choice, the message and `openrouter_metadata`.
Rule 7 and the request rule are shared with the 429 proof (`openrouter_provider/billing_facts.py`).

**BYOK.** BYOK is part of how our OpenRouter account is set up, not of one reply. Prod replies show
`is_byok: false`. If we turn on BYOK for a provider, this rule must change.

## 9. Amendment 2026-10-27: review fixes (after OME-1746)

The review of PR #1571 found three gaps. The owner chose to fix them:

- **No output (condition 6).** Every field of the message except `role` must be empty (absent,
  `null`, `""`, `[]` or `{}`), whatever its name. Output in a field that this spec did not name
  (for example `audio`, `images`, `annotations`) is output. The top-level `output` and `content`
  must also be empty.
- **Paid stage.** A refusal whose `openrouter_metadata.pipeline` has a `plugin` or
  `server_tools` stage keeps the evidence unchanged, the same as the 429 rule.
- **No crash.** The proof gives a result for any value. A stage `type` is read as text wherever
  it is (a string, or text inside a list or object). A value such as `"sNaN"` is not a zero.

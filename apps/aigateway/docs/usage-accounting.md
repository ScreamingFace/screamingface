# Usage accounting

`POST /v1/chat/completions` can return bounded provider-attempt accounting under the top-level
`_aigw` key. This key is reserved by the gateway and replaces any provider-supplied `_aigw` value
in the returned copy; cached provider JSON remains unchanged. OpenRouter and Anthropic are the
initial supported providers.

This contract is pre-beta and may change incompatibly. The wire intentionally carries no numbered
version and no maturity label. This document and the packaged JSON Schema describe the current
contract; consumers must update with pre-beta changes.

## Activation

Accounting is enabled by default for non-streaming calls. Callers do not send an activation header.
Accounting state does not enter provider parameter validation or alter the effective request-cache
key.

Streaming remains available through the existing SSE path without `_aigw` accounting. Supporting
streaming accounting later must not buffer the complete stream or delay its first token.

## Response shape

```json
{
  "_aigw": {
    "usage_accounting": {
      "schema": "aigw.chat_usage_accounting",
      "capture_status": "complete",
      "gateway_call_id": "call_0123456789abcdef0123456789abcdef",
      "cache": {"status": "miss", "reference": null},
      "observed_attempts": 1,
      "rendered_attempts": 1,
      "omitted_attempts": 0,
      "attempts": [
        {
          "schema": "aigw.provider_attempt",
          "attempt_id": "attempt_0123456789abcdef0123456789abcdef",
          "sequence": 1,
          "dispatch_index": 1,
          "attempt_index": 1,
          "provider": "openrouter",
          "requested_model": "openrouter/example/model",
          "response_model": "example/model",
          "provider_response_id": "generation-1",
          "transport": "litellm_async_http",
          "outcome": "succeeded",
          "http_status": 200,
          "latency_ms": 120,
          "usage": {
            "status": "complete",
            "source": "provider_raw_response",
            "input": {"total": 10, "uncached": 10, "cache_read": 0, "cache_write": 0, "cache_write_by_ttl": []},
            "output": {"total": 5, "reasoning": null}
          },
          "pricing_context": {"service_tier": null, "backend": null},
          "direct_cost": {"status": "reported", "amount": "0.001", "unit": "openrouter_credits", "source": "openrouter.usage.cost"},
          "provider_extensions": [],
          "provider_extensions_truncated": false,
          "redirect_hop_count": 0,
          "failure_code": null
        }
      ]
    },
    "request_economics": {
      "schema": "aigw.request_economics",
      "observed_new_attempts": 1,
      "direct_cost_status": "complete",
      "known_direct_cost_subtotals": [
        {"amount": "0.001", "unit": "openrouter_credits", "source": "openrouter.usage.cost"}
      ]
    }
  }
}
```

The packaged authority for exact required fields, enums, bounds and closed-object behavior is
`aigateway/plugins/taxonomy/usage_accounting.schema.json`.

## Attempt meaning

One attempt represents one local provider send-pipeline admission. It proves that the gateway
admitted a send; it does not by itself prove provider receipt, model execution or billing.

- Gateway overload retries have different `dispatch_index` values.
- Hidden LiteLLM resends have different `attempt_index` values in one dispatch.
- Redirect hops remain one attempt and increment `redirect_hop_count`.
- A redirect cycle that is indistinguishable from a hidden resend marks capture `partial`.
- Failed attempts may still carry provider-authored usage or cost and must not be discarded from
  accounting solely because `outcome` is not `succeeded`.

## Status rules

Consumers may treat request cost as complete only when all of these hold:

```text
capture_status == complete
omitted_attempts == 0
direct_cost_status == complete
```

`null` means unknown or not reported, never zero. A cache hit has no new attempts. Its optional
`cache.reference` describes only historical final-response evidence and is explicitly not incurred
in the current request.

A cache row can also carry a standard metadata block. The gateway captures that block at write
time from the raw provider response, before any conversion. The block keeps its own direct-cost
status. One status is `archive_matched`: the amount comes from a real logged call of the same kind
and model, not from this row's own call. `archive_matched` money is never added to `reported`
money.

## Money and precision

Direct cost is provider-authored evidence only. Amounts are canonical non-negative fixed-point ASCII
strings with up to 18 integer and 33 fractional digits.

- Raw JSON decimals are parsed directly as `Decimal` and retain their lexical precision.
- Exact summation uses Decimal arithmetic without a finite context rounding the result.
- Binary float is not an exact money intermediary.
- Converted integer token evidence can remain useful with `source=provider_converted_response`.
- If only a converted floating-point cost remains, it must not be presented as exact direct cost
  unless that carrier is independently proven lossless.
- Cached monetary evidence in `response_json` is never certified as exact direct cost. A cache row
  contains the converted provider-compatible response and cannot prove original raw-JSON
  provenance, regardless of whether its current Python carrier is `Decimal`, `int` or `float`.

### Write-time carve-out for the metadata block

The rule above applies to `response_json`. It does not apply to the `metadata_json` block. The
gateway captures that block at write time from the raw provider response, before any conversion.
The block therefore does prove raw-JSON provenance. A `metadata_json` block is the only cached
monetary evidence the gateway certifies as exact provider-authored cost.

The carve-out holds only for the write-time block:

- A value re-read out of `response_json` stays uncertified, whatever its Python carrier is.
- A block with `direct_cost.status == "reported"` holds the exact provider decimal and its original
  unit. The status vocabulary also includes `absent`, `unavailable`, `invalid` and `unit_unknown`.
- A block with `direct_cost.status == "archive_matched"` holds a real measured amount from a paired
  logged call of the same kind and model. That call is not this row's own call, so the amount is
  not exact provider-authored cost.
- Never add `archive_matched` money to `reported` money. Keep the two totals separate at every
  step. A consumer must not produce a third, combined figure.
- A block with `absent`, `unavailable` or `invalid` status carries no amount. The value is unknown,
  never zero.
- A hit on a row with no block, or with an unreadable block, falls back to the cached-body rule
  above. The gateway never infers a cost from `response_json`.

**Open question — OpenAI and HuggingFace hit references.** Both providers return `None` from
`cache_reference_from_cached_response`, so a hit on one of their rows publishes no cache reference
at all and the stored block is never consulted. Those are two separate locked decisions, not one:
OpenAI cites OME-884, HuggingFace cites OME-791. Each was taken when a cache row had nothing
truthful to say about cost. A write-time block changes that premise, so adopting it for either
provider is now defensible — but doing so re-opens the corresponding decision and must be argued
there, not here. Both stay at `None` until then.

Full raw JSON evidence is parsed only when decoded content is at most 256 KiB. Accounting metadata is
also bounded: at most 64 rendered attempts and 64 KiB for the complete `_aigw` object. Bounds degrade
to explicit partial/unavailable states instead of failing an otherwise successful provider response.

## Provider extensions

Provider-specific audit facts use namespaces such as `openrouter.response_usage` and
`anthropic.usage`. Extensions are bounded, typed, allowlisted scalar facts. They cannot contain raw
provider objects, prompts, generated text, credentials, headers, arbitrary error text or tracebacks.
Generic consumers may ignore all extensions and still interpret the canonical attempt structure.

## Ownership boundary

AIGateway owns observation, normalization, sanitization and request-local summaries. Engine owns
deterministic attribution, run/subtree rollups, persistence, UI and any pricing calculation not
directly authored by the provider response.

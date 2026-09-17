---
id: OME-303
linear_url: https://linear.app/openmined/issue/OME-303/ome-303-per-model-call-usage-accounting-latency-tokens-cost
status: in_progress
type: Feature
priority: High
labels: [aigateway]
created: 2026-08-12
closed:
---

# OME-303 - Per-provider-attempt usage accounting

## Goal

Produce trustworthy per-attempt facts for Engine attribution and rollup without making AIGateway a
pricing, persistence or reporting system. Initial provider support is OpenRouter and Anthropic.

The response contract is evolving. Until the accounting API is declared beta, field names,
requiredness and semantics may change incompatibly. The wire therefore carries no version taxonomy
or maturity label. Plan and specification changes ship with the implementation that adopts them.

Runtime specification: `apps/aigateway/docs/usage-accounting.md`.

## Architecture

The implementation separates two functions:

1. A gateway-owned app-lifetime LiteLLM HTTP observer records local send admissions, redirects,
   hidden resends, response completion and latency into a request-local collector.
2. Provider-owned pure mappers convert bounded raw or converted response evidence into a closed
   provider-neutral taxonomy.

The route attaches `_aigw` only to a returned response copy. Cache rows keep provider-compatible
JSON and never persist accounting metadata. Engine owns USD conversion where the producer has no
provider-authored direct cost, deterministic attribution, run/subtree rollups and persistence.

## Precision policy

- Parse raw JSON decimal values directly as `Decimal`; never reconstruct exact money from
  `Decimal(float)`.
- Preserve exact fixed-point spelling and sum with Decimal arithmetic.
- Prefer raw provider evidence over LiteLLM-converted evidence.
- Converted integer token evidence may be retained with explicit provenance.
- Converted floating-point money is not lossless evidence. If exact raw money is unavailable, mark
  direct cost unavailable unless the carrier is independently proven lossless.
- Cache rows contain converted provider-compatible responses and cannot prove original raw-money
  provenance regardless of their current Python numeric carrier. Cached direct cost is unavailable.
- Full raw JSON parsing is currently bounded to 256 KiB of decoded content. Selective structured
  extraction from larger responses is a follow-up if live measurements justify it.

## Compatibility strategy

- Core taxonomy is closed: unknown core fields are rejected by the packaged JSON Schema.
- New providers map Engine-required concepts into the existing core.
- Provider-specific audit facts use bounded, typed, allowlisted namespaces that generic consumers
  may ignore.
- While pre-beta, incompatible core changes update the schema, fixtures, plan and spec in the same PR;
  no compatibility shim or parallel numbered version is required.
- At beta, compatibility and deprecation policy must be explicitly approved before the taxonomy is
  treated as stable.

## Delivery units

### Completed in this PR

- provider-neutral attempt/token/cost/status value objects and renderer;
- OpenRouter and Anthropic mappers;
- request-local cardinality and app-lifetime transport observation;
- cache-hit historical references that are never current spend;
- exact Decimal arithmetic, bounded metadata, leakage tests and packaged Draft 2020-12 schema;
- taxonomy version suffix removal and registry-driven provider-neutral failure-code conformance.
- default-on accounting for non-streaming chat calls with no activation header;
- unchanged streaming/SSE behavior without accounting metadata.

### Next unit

If streaming accounting becomes necessary, preserve first-token delivery, observe raw SSE usage
without buffering the complete stream, publish final accounting in an OpenAI-compatible final usage
chunk, and classify disconnect/mid-stream failure honestly. Streaming accounting is not required for
the current delivery.

### Follow-ups requiring evidence

- Measure real completion response sizes and raw cost spelling with owner-provided live credentials.
- Confirm ordinary OpenRouter and BYOK cost semantics against live responses before changing the
  current direct-cost unit/source contract.
- Add selective structured extraction for decoded responses over 256 KiB only if measurements show
  that exact cost is otherwise lost in realistic workloads.

## Acceptance

- every observed non-streaming provider send has one ordered attempt or an explicit partial status;
- hidden transport resends remain distinct while redirect hops do not inflate economics;
- unknown is never rendered as zero and cache references are never current spend;
- exact provider-authored money never passes through a binary-float intermediary;
- raw provider content, prompts, credentials, headers and tracebacks cannot enter `_aigw`;
- schema, fixtures, plan and spec contain no accounting version taxonomy;
- adding a provider automatically extends the provider-neutral failure-code conformance check;
- configured AIGateway gates pass.

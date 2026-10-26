---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: aigateway + screamingface-engine
status: in_progress
started: 2026-10-26
finished:
---

# openrouter-pre-output-refusal-zero — price an OpenRouter refusal before output as $0

## Intent

On the lab_bench boards, each run of `claude-opus-5.5` (solo, or in a trio) shows cost "—".
Anthropic refuses some biology questions before the model writes output. Through OpenRouter, that
reply is HTTP 200 with `finish_reason: "content_filter"`, `native_finish_reason: "refusal"`, no
content, no reasoning and **no `usage` key**. OpenRouter keeps no billing record for it (a live
call on 2026-10-26: `/api/v1/generation` gave 404; a control call was found in 20 s). The gateway
records this as `direct_cost: unavailable`, and one unpriced call makes the whole run unpriced.
This unit makes the gateway certify that exact shape as `provider_guaranteed_zero`, and makes the
engine price that certified zero as $0, live and on a cache hit. Spec:
`docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md`.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/openrouter_provider/pre_output_refusal.py` (new): the
  fail-closed proof `proves_pre_output_refusal(raw_response, ...)`.
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/usage_accounting.py`: new source
  constant `PRE_OUTPUT_REFUSAL_SOURCE`; `supplement_openrouter_usage_accounting` certifies the
  refusal on a succeeded HTTP 200 attempt.
- `apps/aigateway/tests/unit/usage_accounting/test_openrouter_pre_output_refusal.py` (new).
- `apps/screamingface-engine/src/screamingface_engine/world/accounting.py`: price a
  `provider_guaranteed_zero` direct cost from the refusal source as $0 (successful attempt and
  cache reference).
- `apps/screamingface-engine/tests/unit/test_pre_output_refusal_pricing.py` (new).
- `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md` (new).

## Test plan

- Gateway: the real raw body (2026-10-26 live call) on HTTP 200 → `provider_guaranteed_zero`,
  `amount "0"`, source `openrouter.pre_output_refusal`, tokens stay unknown; rendered metadata
  carries it as `succeeded_attempt_direct_cost` and is schema valid; the cache-entry metadata
  keeps it for a later hit.
- Gateway negatives (stay `unavailable`/unchanged): a `usage` object present; a reported cost; a
  refusal with reasoning, content or tool calls; `native_finish_reason` other than `refusal`;
  `finish_reason` other than `content_filter`; two choices; non-200; failed; request with a
  potential auxiliary charge; unknown top-level field.
- Engine: a successful attempt with the refusal zero → `Decimal(0)`; a cache hit whose reference
  holds the refusal zero → `AvoidedCost(0, "reported")` (a priced hit); a guaranteed zero from any
  other source stays unpriced (prior test `guaranteed_zero` stays unchanged).

## Acceptance

- A run whose only unknown call is an OpenRouter pre-output refusal is priced (live and replay).
- Mid-stream refusals (with `usage.cost`) keep their reported price.
- All prior tests stay unchanged and green; both stacks' gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (gateway: `pre_output_refusal.py` new, `usage_accounting.py`,
  31 new tests; engine: `world/accounting.py`, 13 new tests; spec + this ledger).
- **Commits:** see the PR (one squash commit).
- **Gates:** `run_gates.py aigateway` ALL GATES GREEN; `run_gates.py screamingface-engine` ALL
  GATES GREEN (2026-10-26). No prior test changed.
- **Deviations:** the engine prices a guaranteed zero only from an allowlisted source (P5), not
  the status alone. This keeps OME-1687 R3 and the prior `guaranteed_zero` test unchanged.
  `world/accounting.py` was already over 450 lines before this unit; it grew by ~20 lines.

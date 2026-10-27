---
ticket: OME-1746
stack: aigateway
status: in_progress
started: 2026-10-27
finished:
---

# openrouter-refusal-metadata — OpenRouter zero proofs read billing facts, not the reply format

## Intent

OME-1738 (PR #1557) prices an OpenRouter refusal before output as $0. The proof accepted only a
fixed set of top-level fields. The gateway sends `X-OpenRouter-Metadata: enabled` on every
OpenRouter call, so each prod reply also carries `openrouter_metadata`, and the proof never
certified in prod. A live call on 2026-10-27 with the gateway headers confirmed the field.

The first version of this unit accepted the field and checked its content. The owner then
decided (2026-10-27): a zero proof checks only the facts that tell if OpenRouter billed the call;
the reply format must not change the result, so "unknown" is rare. This applies to both proofs:
the pre-output refusal ($0, HTTP 200) and the 429 zero-completion insurance (OME-1446).

Specs: `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md` §8 and the 2026-10-27
amendment of `docs/spec/2026-10-06-OME-1446-proven-zero-retry-accounting.md`.

## Planned changes

- `openrouter_provider/billing_facts.py` (new): `reports_a_charge` (a non-zero value under any
  `cost`/`amount` key, anywhere) and `usage_shows_billed_work` (a non-zero value in `usage` outside
  the prompt counts).
- `openrouter_provider/pre_output_refusal.py`: drop field allowlists, type checks and all
  `openrouter_metadata` checks; keep status, request, no usage/error, refusal signal, no output,
  plus `reports_a_charge`.
- `openrouter_provider/zero_insurance.py`: drop field allowlists, type checks, error-object checks,
  router-metadata/pipeline presence, attempt chain and BYOK; keep status 429, request, no output,
  `usage_shows_billed_work`, `reports_a_charge`, no `plugin`/`server_tools` stage.
- `openrouter_provider/response_shape.py`: removed (no shape checks left to share).
- Tests: rewrite this unit's `test_openrouter_pre_output_refusal_metadata.py`; new
  `test_openrouter_proven_zero_billing_facts.py`; remove the format-only cases from prior tests
  (owner approved 2026-10-27).
- `apps/aigateway/docs/usage-accounting.md`, both specs.

## Test plan

- Each format-only case that prior tests kept unknown is now certified (same inputs, new files).
- Stays unknown: a non-zero or text money value in any field; billed work in `usage`, also as
  text ("50"); `usage` not an object; a paid stage type; any output; a request with a potential
  auxiliary charge; usage or an error on the refusal.
- All other prior tests stay green and unchanged.

## Acceptance

- The prod refusal shape is certified; format changes do not make either cost unknown; money
  facts still do; gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see the PR (one squash commit).
- **Gates:** `run_gates.py aigateway --base <merge-base>` ALL GATES GREEN (2026-10-27): ruff, format, pyright, no-enterprise, pytest with coverage; 751 accounting tests pass; the 5 changed prior files pass the append-only check through `.claude/test-change-approvals/OME-1746.json`.
- **Deviations / prior tests changed (owner approved 2026-10-27):** removed the format-only cases
  `unknown-field`, `bad-scalar` (refusal); `malformed-current-chat-server-tool-usage`,
  `conflicting-byok`, `malformed-byok`, `non-boolean-byok`, `test_error_code_must_agree_with_native_429`
  (proven_zero); pipeline-cost `null`/`mapping`, `malformed-output-details`, `mapping-byok-cost`,
  `decimal-code-equal-to-integer`, `wrong-error-type`, `unknown-pipeline-stage`,
  `test_missing_pipeline_…`, `test_malformed_pipeline_…`, `test_router_attempt_chain_…`,
  `test_router_byok_evidence_…` (fail_closed); `router-attempt-bool`,
  `test_unknown_server_tool_counts_are_not_zero` (metadata_shapes); `unknown-zero-cost-field`,
  `null-cost`, `boolean-prompt-tokens` (strict_evidence). Each input is now asserted certified
  in the new files. Still out of scope: the engine signal path (follow-up), old cache rows.

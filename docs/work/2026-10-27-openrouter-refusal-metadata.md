---
ticket: OME-1746
stack: aigateway
status: in_progress
started: 2026-10-27
finished:
---

# openrouter-refusal-metadata — accept `openrouter_metadata` in the pre-output refusal proof

## Intent

OME-1738 (PR #1557) prices an OpenRouter refusal before output as $0. The proof accepts only a
fixed set of top-level fields. The gateway sends `X-OpenRouter-Metadata: enabled` on every
OpenRouter call, so each prod reply also carries `openrouter_metadata`. The proof rejects that
field, so in prod it never certifies and the lab_bench rows stay "—". A live call on 2026-10-27
with the gateway headers confirmed the field on a refusal. This unit accepts the field and checks
its content. Nothing else changes. Spec: `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md`
§8.

## Planned changes

- `apps/aigateway/src/aigateway/plugins/openrouter_provider/pre_output_refusal.py`: allow
  `openrouter_metadata`; when present it must prove `is_byok: false` and contain only known fields.
- `apps/aigateway/tests/unit/usage_accounting/test_openrouter_pre_output_refusal_metadata.py` (new).
- `docs/spec/2026-10-26-openrouter-pre-output-refusal-zero.md`: §8 amendment.
- Cleanups (user request 2026-10-27): new `openrouter_provider/response_shape.py` with the shape
  checks both zero proofs use (`zero_insurance.py` imports them, behaviour unchanged);
  `apps/aigateway/docs/usage-accounting.md` documents the second `provider_guaranteed_zero` case.

## Test plan

- The real 2026-10-27 body (with `openrouter_metadata`) is certified, end to end through the
  collector, and the rendered metadata is schema valid.
- Stays unknown: `is_byok` true, absent or not a bool; an unknown field inside the metadata
  (`pipeline`, `attempts`, a new name); metadata not an object; bad `endpoints`; bad `attempt`,
  `generation_time` or string fields.
- All prior tests stay unchanged.

## Acceptance

- A prod-shape refusal is certified as `provider_guaranteed_zero`; all prior tests green; gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the two cleanups above.
- **Commits:** see the PR (one squash commit).
- **Gates:** `run_gates.py aigateway` ALL GATES GREEN (2026-10-27); 738 accounting tests pass,
  119 zero-insurance tests unchanged and green. No prior test changed. Engine not touched.
- **Deviations:** scope widened by the user to include the two review cleanups. Still out of
  scope: generic native finish reasons, the engine signal path (follow-up), old cache rows.

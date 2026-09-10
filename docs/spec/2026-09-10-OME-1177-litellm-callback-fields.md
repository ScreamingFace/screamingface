---
ticket: OME-1177
---

# OME-1177 — strip new LiteLLM 1.100.0 dynamic callback params

## Problem

litellm 1.100.0 adds three new dynamic callback params to
`initialize_dynamic_callback_params._supported_callback_params`:
`langfuse_environment`, `newrelic_api_key`, `newrelic_region`. aigateway's
`_CALLBACK_DYNAMIC_FIELDS` allowlist in `request_hardening.py` (part of
`DISPATCH_CONTROL_FIELDS`) does not yet strip them from inbound requests. A caller could set
these on a chat request body or `metadata` to redirect where prompt/response telemetry ships —
same exfiltration class as the existing langfuse/langsmith/arize/braintrust/datadog fields.
`packages/screamingface[runtime]` bundles aigateway's source under its own litellm resolution,
so PR #858's litellm 1.98.0→1.100.0 bump reaches this gap immediately on merge, even though
aigateway's own (independently pinned) test suite doesn't yet catch it.

## Design

1. Bump aigateway's own `litellm` pin to ~1.100.0 so its test suite and the bundled runtime
   agree, and so `test_litellm_dynamic_callback_parameter_set_is_covered` actually exercises
   1.100.0's real `_supported_callback_params`.
2. Add the three new field names to `_CALLBACK_DYNAMIC_FIELDS`, following the existing `dd_*`
   comment-block precedent (name the litellm version and feature that introduced them).
3. Add explicit regression tests asserting the three fields are stripped from both request body
   and `metadata` — belt-and-suspenders alongside the exact-set coverage test.
4. Re-verify and bump the two hardcoded `== "1.97.0"` tripwire assertions in
   `test_openai_runtime_guard.py`, confirming every guarded-global field name is still a real
   attribute on the new litellm version before touching the literal.

## Non-goals

- No client-facing API change.
- `packages/screamingface` / PR #858 itself is out of scope — this unit only unblocks it.
- No broader litellm dependency audit beyond what `--upgrade-package litellm` pulls in.

## Tests

- RED: `test_litellm_dynamic_callback_parameter_set_is_covered` and the two `== "1.97.0"`
  assertions fail against the bumped litellm before the fix.
- GREEN: new regression assertions for the three fields (body + metadata); all prior tests
  stay green; version-pin assertions updated only after field-existence re-verification.

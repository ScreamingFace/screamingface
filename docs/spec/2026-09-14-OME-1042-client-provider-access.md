# OME-1042 — Client execution-access preflight

Approved direction: Client draft PR consuming Gateway OME-1195 / #932 through the existing Engine passthrough. No Engine implementation is needed.

Expose ModelDetails.execution_access as `configured`, `missing`, or None (unknown when omitted by an older Gateway). The wire decoder rejects malformed explicit values as model-details discovery errors, never as missing access. Existing model-details calls remain usable for credential-free datasheets; only evaluation turns missing access into ProviderConnectionError.

Evaluate all required Candidate models in the existing preflight, including models with no explicit parameters and nested recipes. Before observers or Candidate dispatch, an authoritative missing status raises ProviderConnectionError with a stable code, provider/model details, and a hint to configure the selected provider/profile (sf.connect for BYOK, hosted profile configuration when applicable). Implement identical sync/async behavior. Do not infer from local credential absence, provider names, or datasheet auth_mode.

Configured and unknown access retain existing behavior. Configured means configuration exists, not that credentials are validated. This compatibility path means older Gateways cannot provide the new early-error guarantee. Existing auth/transport/discovery failures retain their types. Doctor stays independent. Fetch one details document per required Candidate model, reusing admission probes. Parameter-free evaluation now needs these discovery requests too. No separate access endpoint or inference request.

Approved review rebase (2026-09-16): combine all-model access preflight and admission-document reuse with main's answer-seed validation. Keep prefetched keyword-only alongside answer_seed, use explicit None handling for sync lookups, and validate both guarantees before observers/dispatch. Shared test-helper extraction remains separate. Run combined regressions and full Client gates, then push the existing PR without merging.

## Approved CI compatibility follow-up — 2026-09-17

Keyless response-cache replay must remain executable without provider credentials. Its test-only discovery adapter omits live execution_access metadata to exercise supported legacy/unknown compatibility, while real Gateway chat/cache/error paths and production access checks remain unchanged. Cache misses must still fail with profile_not_found and no provider dispatch.

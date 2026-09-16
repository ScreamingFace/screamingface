# OME-1042 — Client implementation plan

1. Add failing tests at the model-details decoder and public Client.evaluate/AsyncClient.evaluate boundaries, including zero-dispatch proof and composed models.
2. Add optional validated access metadata to ModelDetails and decode the Gateway field.
3. Check that metadata in existing model preflight before parameter validation and Candidate dispatch; retain unknown compatibility.
4. Run focused tests, then all screamingface gates (including notebook/distribution checks).
5. Record wisdom/validation, commit, push with SSH keepalives, and open a Client-only draft PR linked to Gateway #932.

Approved review rebase (2026-09-16): combine all-model access preflight and admission-document reuse with main's answer-seed validation. Keep prefetched keyword-only alongside answer_seed, use explicit None handling for sync lookups, and validate both guarantees before observers/dispatch. Shared test-helper extraction remains separate. Run combined regressions and full Client gates, then push the existing PR without merging.

## Approved replay follow-up — 2026-09-17

Add a test-only ASGI response adapter for successful Gateway model-parameter discovery; remove only context.execution_access. Boot it only in CacheSeededGateway via uvicorn app-dir. Add focused adapter and real replay assertions, retain existing goldens/miss contracts, run Client gates and replay, and commit. The independent Gateway deadline flake is retried without broadening this package-only change.

---
ticket: OME-1042
stack: screamingface
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1042 — Keyless replay access compatibility

## Intent

Fix PR933 golden replay failures after introducing provider access preflight. Owner approved the CI follow-up on 2026-09-17. Replay intentionally has no provider credentials and serves pre-credential cached answers; live-access missing therefore blocks the harness before its cache is reached.

## Planned changes

- Add a test-only Gateway app wrapper under packages/screamingface/tests/e2e/harness that omits context.execution_access from successful model-parameter discovery, exercising the Client's supported unknown/legacy compatibility path.
- Wire only CacheSeededGateway to this wrapper. No production Client, Engine or Gateway edits, dummy credentials, or metadata claiming configured access.
- Add unit and real replay regression cases. Preserve all existing cache-miss and golden assertions.
- Document the narrow replay discovery normalization. Retry the unrelated Gateway deadline-flake job separately.

## Test plan

- RED: existing golden replay logs show ProviderConnectionError before dispatch; new synthetic replay discovery case must assert unknown access while real cache misses still fail profile_not_found.
- Unit cases: successful discovery removes only the access field; all other metadata, paths and errors are preserved.
- Run full Client gates and available real Docker replay lane, including golden fixtures.

## Acceptance

- Replay reaches cached answers without credentials or external provider requests.
- Production missing-access rejection remains tested and unchanged.
- Client gates and real replay pass; commit and push the harness-only follow-up.

## Outcome

- **Actual files:** test-only ASGI discovery adapter, replay Gateway launcher, five adapter unit cases, appended real-stack discovery test, replay README, shared spec/plan/task mirror and this ledger.
- **Commit:** `test(screamingface): preserve keyless cache replay with access preflight` (this commit).
- **RED:** actual Docker Gateway discovery regression failed on execution_access presence before the fix; five new unit cases failed before the adapter existed. The CI trace independently showed ProviderConnectionError before dispatch.
- **GREEN:** five adapter cases pass; real Docker replay lane 135 passed, six board skips without explicit assets. Board rerun with available assets: draco-3pass, ifeval and healthbench-worst30 all match goldens (3 passed); GDPval assets unavailable locally, two other boards have no committed fixtures. Existing cache-miss and trace-correlation assertions pass unchanged.
- **Gates:** Client Ruff lint/format, Pyright, full pytest/95% coverage, notebook checks, package build and distribution checks all pass.
- **Wisdom/confidence:** no production-code changes, no provider keys, no fabricated configured-access claim. Tests and docs state the narrow legacy/unknown discovery compatibility path. Original golden/cache-miss assertions and fixtures are preserved. Independent Standards and Spec reviews found no material findings.
- **Deviations:** the append-only scanner flags the authorized existing test-harness launcher update and README. Ran remaining gates with --skip-append-only for this narrow exception; no old test assertions were edited. Retried unrelated Gateway deadline failure (35160149290); Python 3.13 repeated the existing timing failure, recorded separately rather than suppressed. No Linear comments.

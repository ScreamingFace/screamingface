---
ticket: OME-958
stack: screamingface-engine
status: done
started: 2026-08-24
finished: 2026-08-24
---

# OME-958 — Hosted provider availability from caller profiles

## Intent

Replace deployed Engine's catalogue-shaped provider status with a truthful caller-scoped
projection of existing AI Gateway profiles, while preserving local BYOK behavior and every public
Engine connection type.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/connections/aigateway.py` — profile decoding
  and projection behind an explicit listing source.
- `apps/screamingface-engine/src/screamingface_engine/connections/profile_availability.py` and
  `provider_id.py` — focused profile projection and shared provider-ID validation.
- `apps/screamingface-engine/src/screamingface_engine/connections/upstream_errors.py` — existing
  secret-free upstream status translation extracted to keep the adapter focused.
- `apps/screamingface-engine/src/screamingface_engine/connections/__init__.py` — composition input.
- `apps/screamingface-engine/src/screamingface_engine/app.py` — deployed profile-source wiring.
- `apps/screamingface-engine/src/screamingface_engine/local.py` — explicit local BYOK-source wiring.
- `apps/screamingface-engine/tests/unit/test_connections_aigateway.py` — caller/profile contract,
  precedence, malformed-response, and local-regression tests.
- `apps/screamingface-engine/tests/unit/test_local_aigateway_connection.py` and focused production
  composition coverage — source-selection tests.
- `docs/{tasks,spec,plan,work}/` — required OME-957/958/960 records.

## Test plan

- RED: two callers with different authenticated profiles receive different Connected providers.
- RED: authenticated, pending, error, and absent profile states project with deterministic
  precedence; unknown providers cannot enter the catalogue.
- RED: malformed profile responses fail as `ConnectionBadResponse` without leaking payloads.
- RED: deployed composition selects profiles; local composition retains managed connection rows.
- GREEN: existing adapter, REST, local-mode, and full Engine tests remain unchanged and pass.

## Acceptance

- OME-958's Linear acceptance criteria and approved spec are satisfied.
- No AI Gateway or public `/v1/connections` schema change is introduced.
- ScreamingFace Engine gates pass at or above their existing coverage threshold.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the planned composition, adapter, profile projection, shared provider-ID
  validation, upstream error translation, focused tests, and OME-957/958/960 SDLC artifacts.
- **Commits:** this implementation commit — `feat(screamingface-engine): derive hosted provider availability`.
- **Gates:** `run_gates.py screamingface-engine` — ALL GATES GREEN; full suite 2,007 passed,
  6 skipped; focused connection suite 59 passed; Pyright 0 errors.
- **Deviations:** extracted existing upstream status translation after the initial implementation
  pushed `aigateway.py` above the 450-line focus limit; final adapter is 440 lines. No AI Gateway
  or public Engine schema change was required.

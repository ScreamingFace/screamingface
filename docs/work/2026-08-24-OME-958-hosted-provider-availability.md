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

## Review follow-up

### Planned changes

- Reject connect, OAuth-start, and disconnect before any upstream request when profile-backed
  hosted listing makes the adapter read-only.
- Accept unknown sibling fields around the required `profiles` list.
- Make `listing_source` required at the builder seam so production and local composition cannot
  silently inherit a default; retain the adapter's legacy default for direct internal use.
- Add append-only tests for all three hosted mutations, tolerant profile envelopes, and the
  unchanged mutable local path.

### Test plan

- RED: each hosted mutation raises a safe 4xx connection error and sends zero Gateway requests.
- RED: profile envelopes with harmless object/paging siblings still project availability.
- GREEN: existing local list/connect/OAuth/disconnect tests and the full Engine suite remain
  unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the planned composition, adapter, profile projection, shared provider-ID
  validation, upstream error translation, hosted read-only mutation guard, focused tests, and
  OME-957/958/960 SDLC artifacts.
- **Commits:** `feat(screamingface-engine): derive hosted provider availability`; review follow-up
  `fix(screamingface-engine): reject hosted provider mutations` (this commit).
- **Gates:** `run_gates.py screamingface-engine` — ALL GATES GREEN; full suite 2,007 passed,
  6 skipped on the initial implementation; review follow-up also passed the complete gate runner
  and 57 focused adapter tests; Pyright 0 errors.
- **Deviations:** extracted existing upstream status translation after the initial implementation
  pushed `aigateway.py` above the 450-line focus limit; final adapter remains within the limit.
  The follow-up requires `listing_source` at the exported builder seam while retaining the
  adapter's legacy default for direct internal construction; this preserved every prior test and
  still makes both production composition omissions fail. No AI Gateway or public Engine success
  schema change was required.

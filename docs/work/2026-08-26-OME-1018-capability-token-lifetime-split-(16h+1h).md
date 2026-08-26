---
ticket: OME-1018
stack: repo
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1018 — Capability-token lifetime split (16h+1h)

## Intent

Split the capability token's lifetime from its mint-freshness window so a Run's
owner can re-attach, stop, or redeem for the Run's whole life. Today `exp = iat +
iat_window_s` (60 s), so every control path dies 60 s after mint — the root cause of
the 2026-08-26 orphaned-Run incident (spec §2).

## Planned changes

- `auth/jwt.py` — `JwtCodec` gains `capability_lifetime_s`; `sign()` sets
  `exp = iat + capability_lifetime_s`; `verify()` iat check becomes future-skew only
- `config.py` — new `capability_lifetime_s: int = 58_800`; re-document `iat_window_s`
- construction sites: `auth/dependencies.py`, `rest/routes.py`, `ws/endpoint.py`
- `tests/unit/test_auth.py` — boundary table (exp-1/exp, future-iat skew) + deliberate
  flips; 13 other test files get the mechanical `LIFETIME_S` param (no semantic change)

## Test plan

- RED: boundary table against new semantics fails on old codec
- GREEN: accept `exp - 1`, reject at `exp`; reject future iat beyond window; the
  OME-1017 conflation pin flips to verify

## Acceptance

Full engine unit suite green; the 60 s age rejection no longer exists anywhere.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (jwt.py, config.py, 3 call sites, test_auth.py + 14
  mechanical test patches).
- **Commits:** (added by commit step)
- **Gates:** engine unit suite 2037 passed / 5 skipped; full stack gates at epic end
- **Deviations:** none — the 14 other construction sites in tests were patched
  mechanically (uniform `LIFETIME_S` constant); no semantic flips outside test_auth.py
  were needed, confirmed by the full green run.

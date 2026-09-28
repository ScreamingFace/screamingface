---
ticket: OME-1378
stack: analytics
status: done
started: 2026-09-25
finished: 2026-09-25
---

# Keep bridge consent controls reachable when ingestion is disabled

## Intent

Fix PR #1072's readiness regression: an enabled bridge must keep the pod ready
while event delivery is disabled so Kubernetes can route consent and opt-out.
User explicitly authorized fixing this and opening a PR. Related to OME-1378,
under analytics epic OME-1305.

## Planned changes

Readiness predicate in api.py, new append-only regression tests, README contract,
spec and plan. No deployment configuration changes.

## Test plan

Readiness matrix across ingestion/bridge enabled and draining states; actual
consent decline reachable while both event paths reject delivery; shutdown
remains not-ready. Mock upstream only. Run analytics gates and chart verification.

## Acceptance

An enabled, non-draining bridge is ready regardless of event delivery setting.
Both features disabled or draining is not-ready. Consent can be declined without
enabling forwarding. All previous tests remain unchanged and pass.

## Outcome

- **Actual files:** readiness predicate, README, new test_bridge_readiness.py,
  spec/plan/ledger as planned. Existing tests unchanged.
- **Commits:** `fix(analytics): keep bridge ready when delivery is disabled` (this commit).
- **Gates:** RED: 2 failed, 7 passed; GREEN: all 9 new regression cases passed.
  Full analytics gate runner ALL GATES GREEN: append-only, lock, lint, format,
  types, full tests with >=95% branch coverage, distribution build. Existing Helm
  checks and diff whitespace validation pass.
- **Review:** one predicate, no extra abstraction or deployment changes. The matrix
  tests all enabled/draining combinations; integration verifies actual consent,
  rejected forwarding on both event routes, and lifecycle shutdown. No secrets,
  schema changes or broadened event admission. Meets the approved bridge contract.
- **Deviations:** reused existing OME-1378 for this same-component bridge correction;
  no new issue. Dev activation and browser acceptance remain tracked in OME-1379.

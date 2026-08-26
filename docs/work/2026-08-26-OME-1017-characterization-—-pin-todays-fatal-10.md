---
ticket: OME-1017
stack: repo
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1017 — Characterization: pin today's fatal 1012 and the dead abort sweep

## Intent

Pin the incident behavior this epic removes, before any fix, so R2/R4 flip
assertions deliberately. A close-1012 mid-Run is fatal today; the abort sweep's
`DELETE /` 401s on a capability older than 60 s and the engine keeps spending.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_auth.py` — add the iat/exp conflation pin
- `packages/screamingface/tests/test_run_resume_reconnect.py` — new self-contained stub;
  pins fatal 1012, rejected `cancel_active`, sweep note

## Test plan

- Engine: a forged token with old `iat` and future `exp` is rejected by the age check
  (passes today; R2 flips it to accept)
- SDK: close 1012 → `ExecutionError(websocket_disconnected)`, exactly one handshake
- SDK: `cancel_active()` with a 401-rejecting server raises `ExceptionGroup`
  containing `AuthenticationError`
- SDK: `_run_candidates_sync` abort path attaches the sweep failure as a note and
  re-raises the original error

## Acceptance

All four characterizations green on unchanged code; each names the spec section that
later flips it.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (2 files).
- **Commits:** (added by commit step)
- **Gates:** unit-level only; full stack gates run at epic end
- **Deviations:** none — HTTP/1.0 default on the stub handler needed an explicit
  `protocol_version` (websockets refuses HTTP/1.0 handshakes), a harness detail, not a plan deviation.

---
ticket: unfiled
stack: screamingface
status: done
started: 2026-09-30
finished: 2026-09-30
---

# e14-final-packages-screamingface — the SDK reads the Engine's top-level problem `code` (RP-X2)

## Intent

The E14 contract (contracts.md, "Error bodies", Engine + Clients) says the Engine puts its
refusal codes (`replay_grant_too_large`, `replay_grant_ambiguous`, `replay_unsupported`) in the
top-level problem member `code`, and that "the SDK maps the error by `code` first". The SDK
start-error path took the code from the problem `type` field, which the Engine always sets to
`about:blank`. A caller who branches on `error.code` never saw the E14 code. This unit makes
`_problem_parts` prefer a non-blank top-level `code`, and fall back to `type` when `code` is
absent, so every existing code stays the same.

## Planned changes

- `packages/screamingface/src/screamingface/_engine/transport.py`: `_problem_parts` prefers `problem["code"]`.
- `packages/screamingface/tests/test_replay_refusal_codes.py`: new tests.
- `docs/work/2026-09-30-e14-final-packages-screamingface.md`: this ledger.

## Test plan

- RED first: for each of the three C1 codes, sync (`_start_sync`) and async (`_start_async`), the raised
  `ExecutionError.code` is the C1 code and `.status` is the HTTP status.
- Fallback: a problem body with no `code` keeps `type` as the code; a blank or non-string `code` falls back to `type`.
- The refusal is not retried as a capacity wait (no Retry-After) — one send only.

## Acceptance

- The three tests pass sync and async; all prior tests pass; all screamingface gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see `git log` on `final/packages-screamingface` (fix(sdk): read the Engine problem code first).
- **Gates:** run_gates.py screamingface: ALL GATES GREEN (needs `uv sync --extra notebook` for pyright in a fresh worktree).
- **Deviations:** none. Open question left out of scope: whether `replay_unsupported` (503) should be `permanent=True`; it stays `permanent=False` (status < 500 rule) pending a product decision.

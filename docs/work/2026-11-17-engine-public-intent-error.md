---
ticket: OME-1949
stack: python
status: done   # planned | in_progress | done | blocked
started: 2026-11-17
finished: 2026-11-17
---

# engine-public-intent-error — report intent_error on the synchronous url4 answer

## Intent

A gateway refusal (blind model) reaches a sync url4 caller as `internal_error`. Report the code,
withhold the message. Spec: `docs/spec/2026-11-17-engine-public-intent-error.md`.

## Planned changes

- Plan: `docs/plan/2026-11-17-engine-public-intent-error.md`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `apps/screamingface-engine/src/screamingface_engine/error_text.py`,
  `.../rest/routes.py`, `apps/screamingface-engine/tests/unit/test_terminal_error_detail.py`.
- **Commits:** `b546c09f5` fix(engine): report intent_error on the synchronous url4 answer, message withheld.
- **Gates:** ruff, ruff format, pyright 0 errors; engine pytest 9628 passed, 368 skipped.
- **Proof:** the paid image-input matrix (OME-1950) with this diff applied: every text-only url4 cell
  reads `refused` (`intent_error`, 0 gateway calls) instead of `internal_error`.
- **Deviations:** none; HTTP status stays 502 (spec §4).

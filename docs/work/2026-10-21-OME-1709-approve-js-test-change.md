---
ticket: OME-1709
stack: repo
status: planned
started: 2026-10-21
finished:
---

# OME-1709 — let the append-only gate approve an exact .js test change

## Intent

Replace the stack-wide `--skip-append-only` / `--no-verify` escape for owner-approved portal-test
changes with the existing byte-exact manifest approval, and make the approval tests run in the repo
gates. Unblocks `OME-1655`. Spec: `docs/spec/2026-10-21-OME-1709-approve-js-test-change.md`.

## Planned changes

- `.claude/scripts/approved_test_changes.py` (`.js` under `tests/`).
- New `.claude/scripts/tests/test_approved_js_change.py`.
- `.claude/sdlc.local.md` repo gates: the three approval test files.

## Test plan

Spec "Tests".

## Acceptance

As on the ticket.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

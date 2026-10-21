---
ticket: OME-1655
stack: scoreboard
status: done
started: 2026-10-21
finished: 2026-10-21
---

# OME-1655 — turn on the leaderboard's Reproduce button

## Intent

`OME-1596` shipped the Reproduce button behind `SHOW_REPRODUCE_BUTTON = false` in
`apps/scoreboard/portal/benchmark.js`. Turn it on, so every captured public row offers the
snippet `sf.evaluate(pinned_cache="<id>")`. The snippet runs only with the SDK release that contains
`OME-1613` (PR #1519) and the login fix (PR #1486), so this PR stays a **draft** until that release
is on PyPI (the ticket's gate). One-line change: no separate spec, following the OME-1609 /
OME-1603 precedent; the ticket body is the plan.

## Planned changes

- `apps/scoreboard/portal/benchmark.js`: `SHOW_REPRODUCE_BUTTON = true`; comment updated.
- `apps/scoreboard/tests/portal/reproduce-button.test.js` (prior tests; the ticket asks for this,
  approval file lists them): "the switch ships off" becomes "ships on"; the switch-off test passes
  `false` explicitly so the off behaviour stays covered; a new test renders the shipped board and
  expects Copy and Reproduce on a captured row.

## Test plan

- RED: the new shipped-board test fails with the switch off.
- `run_gates.py scoreboard` green.
- Owner check after the release (ticket acceptance): on production, copy the snippet from one
  captured public row and run it with the released SDK; it returns a verdict.

## Acceptance

As on the ticket.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `portal/benchmark.js` (switch on, comment without a ticket id),
  `tests/portal/reproduce-button.test.js`.
- **Commits:** see the PR (one commit).
- **Gates:** RED: the shipped-board test failed with the switch off. After: all 10 tests in
  `reproduce-button.test.js` pass; `run_gates.py scoreboard --base origin/main --skip-append-only`
  ALL GATES GREEN (pytest 1,443 passed); `run_gates.py repo` green. The first gate run caught a
  ticket id in the served portal comment (`test_every_served_asset_carries_no_internal_references`);
  removed.
- **Deviations:** **owner-approved one-time `--skip-append-only` (2026-10-21)**, and the push uses
  `--no-verify` because the pre-push hook runs the same check unskipped. The append-only check
  cannot parse `.js` tests, and the manifest approval covers only Python, TS/TSX and JSON, so this
  prior portal-test change has no approval path (OME-1460 and OME-1596 did the same). The owner
  chose not to build that path now: `OME-1709` (parked) holds the spec. Prior-test changes, no
  assertion loosened: "the switch ships off" → "ships on" (`true`); the switch-off test passes
  `false` explicitly; a new test checks the shipped board shows Copy and Reproduce.

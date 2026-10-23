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
`OME-1613` (PR #1519) and the login fix (PR #1486). SDK 0.1.7 now satisfies that release gate,
and the PR is ready for review (2026-10-23). One-line change: no separate spec, following the OME-1609 /
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

## Implementation outcome

- **Actual files:** as planned: `portal/benchmark.js` (switch on, comment without a ticket id),
  `tests/portal/reproduce-button.test.js`.
- **Implementation commit:** `360a81aaa83fe544df42f294926ed075e1fa6651`; see the PR for tracking updates.
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

## Release readiness and independent review — 2026-10-23

- SDK **0.1.7** is published on PyPI. The downloaded wheel's SHA256 matched PyPI's digest;
  inspection confirmed the public `evaluate` signatures accept `pinned_cache` and `score_id`,
  and Access login forwards the challenged path. This was artifact inspection, not a live replay.
- Independent review of `360a81aaa83fe544df42f294926ed075e1fa6651` found no actionable defects
  in button eligibility, rendering, clipboard handling, or the backend pinned-cache contract.
- Validation: all **148 portal tests** passed, including all **10 Reproduce tests**; the reviewed
  head's relevant GitHub CI checks were green. The docs-only follow-up does not change runtime
  code or tests.
- [PR #1522](https://github.com/ScreamingFace/screamingface/pull/1522) is out of draft mode because
  the SDK release prerequisite is met. The task remains open pending merge, scoreboard
  deployment, and the production copied-snippet check.
- Remaining acceptance: run the snippet from a captured public production row with the released
  SDK and confirm its verdict; verify the `OME-1614` public-docs replay examples and update their
  sidebar source baseline to that verified release. No live replay or docs example execution is
  claimed here. The ledger's `done` status records implementation completion only.

## Review fixes — 2026-10-23

Dmitry's review of `95629f901` found that the mobile stylesheet hides the Run column and
that the tooltip promises $0 without requiring a replay-capable Engine/Gateway. Both findings
are accepted. The earlier independent review missed these conditions.

Plan: remove the narrow-screen rule hiding the Run column so the existing keyboard-scrollable
table exposes Copy and Reproduce at every width. Replace the absolute cost promise with a
replay description that names the compatible Engine/Gateway prerequisite. Add a stylesheet
regression covering nested responsive rules, update the pinned tooltip expectation, and add
a rendered-copy assertion. Verify the real page at mobile and desktop widths with Playwright,
then run the scoreboard and repository gates. No live or paid replay is needed for these fixes.

Outcome:

- Removed the `max-width: 639px` rule hiding `.col-run`. The existing table scroll region keeps
  both actions reachable without adding a second mobile-only control.
- The tooltip now describes replay and explicitly requires a replay-capable Engine and Gateway;
  it no longer promises an unconditional price.
- RED: the new parsed-stylesheet regression failed on the mobile `display: none` rule; the
  rendered-tooltip checks failed on the old $0 copy. GREEN: the stylesheet check and all 11
  focused Reproduce tests passed after the fixes.
- Playwright against real local portal assets and mocked leaderboard responses passed at
  375, 639, 640 and 1280px in light and dark themes. Checked visible Copy/Reproduce actions,
  keyboard focus and horizontal scrolling to the mobile action cell, absent Reproduce on an
  uncaptured row, and exact clipboard text. A direct mobile click also copied the snippet.
  Mobile screenshots were visually inspected in both themes.
- Full scoreboard gates passed: Ruff, formatting, Pyright, pytest with coverage, and all portal
  suites. Repository gates and `git diff --check` passed. Pyright initially caught an invariant
  `list` annotation in the new CSS helper; changing its input to `Iterable` fixed that typing
  error before the successful full run.
- The review-requested change to the existing tooltip assertion is within the owner's request
  to fix the review. This branch still uses its documented `--skip-append-only` path because
  the gate cannot parse changed JavaScript tests; no assertion was removed or weakened.
- The earlier clean-review result is historical, not approval of the revised head. The fixes
  await GitHub CI and reviewer recheck. Deployment and live replay/docs acceptance remain open.

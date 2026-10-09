---
ticket: OME-1425
stack: scoreboard
status: done
started: 2026-10-08
finished: 2026-10-08
---

# OME-1425 — "Closed weights" meets WCAG AA contrast in the light theme

## Intent

The leaderboard's "Closed weights" label is 2.77:1 on the light background, below AA. Give it a legible tone, keep open and closed distinct, and pin both with a test. Part of OME-1282, the epic about showing who wins the open-weights frontier.

## Planned changes

- `apps/scoreboard/portal/portal.css`: closed modifier at `--ink-2`; open rule raised to `:not(.on)` specificity.
- `apps/scoreboard/portal/benchmark.js`: closed rows get `status--closed`.
- `apps/scoreboard/tests/unit/test_portal_weights_contrast.py` (new).
- `apps/scoreboard/pyproject.toml` + `uv.lock`: `tinycss2` dev dependency.

## Test plan

- Closed rule selector and colour, parsed from `portal.css`.
- Both modifier rules beat `.status:not(.on)` on specificity.
- Resolved `--ink-2` is at least 4.5:1 on `--bg` and `--surface`, light and dark, from `tokens.css`.

## Acceptance

- Spec acceptance in `docs/spec/2026-10-08-OME-1425-closed-weights-contrast.md`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** this PR.
- **Gates:** `ruff check` and `ruff format --check` clean; `pyright` 0 errors; `pytest` 968 passed, 9 skipped, coverage 90.35%; node portal suites 82/82. The new test failed 2 of 9 before the CSS change (closed rule missing, open rule selector not found).
- **Deviations:**
  - The first pass put `OME-1425` in the CSS and JS comments. `test_every_served_asset_carries_no_internal_references` caught it, and the comments now describe the reason without the ticket id.
  - Not checked in a browser: the chrome-devtools MCP was not connected. The owner should look at a draco-3pass board row in the light theme.

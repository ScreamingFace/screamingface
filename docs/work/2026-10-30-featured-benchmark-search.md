---
ticket: OME-1761
stack: scoreboard
status: in_progress
started: 2026-10-30
finished:
---

# Featured benchmark search

## Intent

Make the existing benchmark picker find matching featured boards, as approved by
Filip's request to proceed with OME-1761 on 2026-10-30.

## Planned changes

- `apps/scoreboard/portal/main.js`: pass the listed catalog to the picker; use it for nonblank searches.
- `apps/scoreboard/tests/portal/benchmark-picker-search.test.js`: exercise the actual renderer and input handler.
- `.claude/sdlc.local.md` and `.github/workflows/scoreboard-tests.yml`: register the new test.
- Spec, plan, and task mirror for this unit.

## Test plan

First reproduce missing featured results through `ScorePortal.renderTabStrip` in a
minimal DOM harness using real leaderboard logic. Cover featured/nonfeatured matches,
private exclusion, whitespace/case, blank reset, result uniqueness, links and active
indication. Run the scoreboard gate runner and a browser smoke check if available.

## Acceptance

IFEval, HealthBench and both DRACO boards are searchable. Blank queries retain the
overflow list, private boards stay excluded, and navigation/active indication work.

## Outcome

- **Actual files:** as planned; production change is limited to the picker's catalog argument and search-pool selection.
- **Commits:** prepared as `fix(scoreboard): include featured benchmarks in picker search`.
- **Gates:** `uv run .claude/scripts/run_gates.py scoreboard` — ALL GATES GREEN
  (append-only check, Ruff lint/format, Pyright, full pytest with 80% coverage floor,
  and all registered portal tests). Mirror status gate and `git diff --check` passed.
- **Regression evidence:** before the fix, 7 of 9 new tests failed due to missing featured
  results; afterward all 9 passed. Existing tests remain unmodified.
- **Browser:** Playwright against the live public catalog with only main.js replaced
  by this checkout in the browser session. IFEval and HealthBench returned; DRACO
  returned both boards; case/whitespace matched; clearing restored 82 overflow links;
  unmatched search showed the empty state; active indication and result navigation worked.
  No deployed files changed. Screenshot attached to the Linear implementation comment.
- **Wisdom review:** visibility filtering stays in renderTabStrip; the existing matcher
  remains the single matching implementation. No dependency, API or schema changes.
- **Deviations:** isolated worktree is under /tmp to preserve the user's existing checkout.
  Existing ticket and explicit go-ahead provided scope approval. Implementation complete;
  ledger remains in progress until PR review/merge and ticket closure.

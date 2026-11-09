---
ticket: OME-1762
stack: scoreboard
status: done
started: 2026-10-30
finished: 2026-11-03
---

# Close benchmark search with Escape from results

## Intent

Keyboard users must be able to dismiss the benchmark picker from any result and
return to its trigger. Filip authorized continuing with clear leaderboard fixes.

## Planned changes

- `apps/scoreboard/portal/main.js`: handle Escape on the panel as well as its trigger.
- New `apps/scoreboard/tests/portal/benchmark-picker-keyboard.test.js`: actual renderer
  with bubbling DOM events; register it in `.claude/sdlc.local.md` and
  `.github/workflows/scoreboard-tests.yml`.
- Spec, plan and existing issue mirror.

## Test plan

Failing-first result-link Escape regression. Cover input, trigger, filtered/rebuilt
results, visibility and aria-expanded, non-Escape keys, outside clicks and focus
leaving. Verify real Tab and Enter navigation in Chromium using local production
scripts; run all scoreboard gates.

## Acceptance

Escape from any part of the open disclosure closes it and focuses the trigger.
Other navigation and dismissal behavior stays intact. No changes to search scope.

## Outcome

Implementation complete; PR review and merge pending.

- Actual files match the plan. The production change moves one keydown listener
  from the search input to its containing panel; existing close/focus logic is reused.
- RED: 3 result-link Escape failures, 7 passing controls. Chromium reproduced the
  original state: focused MMLU, panel visible, aria-expanded=true after Escape.
- GREEN: all 10 DOM tests pass; all scoreboard gates pass (append-only, Ruff,
  format, Pyright, full pytest with coverage floor, and portal Node tests).
- Chromium: 7 checks pass using production scripts in a local fixture: Escape
  from filtered result/input/last result/trigger, Tab out, outside click, and
  Enter following the result URL. Panel visibility, aria-expanded, and focus checked.
- Mirror status check and git diff whitespace check pass.
- Commit message: `fix(scoreboard): dismiss benchmark picker with Escape from results`.
- Deviations: none. No migration, dependency, visual design or search-scope changes.

## Wisdom review

The containing panel receives bubbling events from existing and newly rendered
results, so no per-link listeners or duplicate Escape handlers are needed. Other
keys are neither intercepted nor canceled. Existing tests are unchanged. Native
browser checks supplement the small DOM harness, which does not simulate the
browser's default Tab traversal or link activation. Public artifact and rendering
safety rules are untouched.

## Review follow-up — 2 November 2026

Resolve the test-command merge conflict with OME-1761 by registering the keyboard suite as a separate explicit command/CI step. Preserve both suites without stacking PRs or changing picker behavior. Verify the combined tree and local scoreboard gates.

Authorized by Filip: “please fix the issues you feel are real ones”. Run regression tests and full scoreboard gates before committing. Outcome: All scoreboard gates green, including all ten keyboard regressions. The keyboard suite now has a separate explicit command in local gates and CI, away from the shared search-test list. No application or test assertion changes in this follow-up.

## Closure — 2026-11-05

Merged [PR #1621](https://github.com/ScreamingFace/screamingface/pull/1621) on 2026-11-03 as
`ffdc7e93f8f17e7622db0148c51982eca1e6a720`. Linear is Done.

---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-09
finished: 2026-11-09
---

# UI merge conflict

## Intent

Make PR 1644 mergeable against main without adding the separately prepared layout redesign.

## Planned changes

Rebase existing commits and combine independent CSS additions. Preserve tests and all current main behavior.

## Test plan

Inspect the failed rebase, compare patches after resolution, run existing scoreboard and repo gates. Browser-check representative mixed data at 1440px/390px, light/dark. No new tests for mechanical conflict resolution.

## Acceptance

No conflicts, gates green, mixed rows retain reviewed behavior. Push only the PR branch as FilipBolt; no merge or Linear changes.

## Outcome

Rebased the six reviewed commits onto main (`f472afc80`), retaining both the incoming catalog-control styles and the existing external-result styles. The conflict was confined to the end of `portal.css`. Range-diff against reviewed head `addec1cdd` shows CSS context changes in two commits and four unchanged commits; no behavior or test changes were introduced by resolution.

Scoreboard and repository gates passed, including lint, formatting, type checks, Python coverage, all portal tests, and repository guard tests. Gates used `--base a6be21c59`, the rebased reviewed head, because the main baseline flags the PR's already-reviewed launch-copy test changes. The range-diff independently confirms that this resolution preserves those tests.

Inspected mixed-board previews at 1440px and 390px in both light and dark themes. Six ranked rows remain: four community runs with their actions and two external results with safe source links and no run buttons. The existing comparison disclosure and horizontally scrollable mobile table remain intact. Screenshots are local ignored artifacts, not committed.

The separate Source/shared-note layout redesign is not included. No merge or Linear update is part of this task.

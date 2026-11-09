---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-05
finished: 2026-11-05
---

# Rebase external leaderboard rows

## Intent

Owner requested resolving PR #1644's conflicts with current main and rerunning
checks. Preserve the approved shared-table behavior, gray rows, normal ranks,
Original result links and existing Copy/Reproduce actions. Existing specification
and plan for OME-1309 remain the implementation contract.

## Planned changes

Rebase the three PR commits from `f9a9d19ca` onto main `b972231da`; reconcile
overlapping portal assets and gate registration while preserving current main's
behavior. Push only this PR branch with an explicit lease after validation.

## Test plan

Inspect conflict resolutions against both sides; run the full scoreboard gate
runner, external-result tests in four time zones and applicable repo checks.
Verify GitHub mergeability and checks after pushing as FilipBolt.

## Outcome

- Rebased all three commits onto `b972231da`. Only the test-list lines in
  `.claude/sdlc.local.md` and `.github/workflows/scoreboard-tests.yml` conflicted;
  retained main's picker tests and this PR's external-result tests in both.
- `git range-diff` confirms that only those conflict resolutions changed the patch
  series; the shared-table implementation and link wording replayed unchanged.
- Full scoreboard and repository gate runners: ALL GATES GREEN against the new
  base. Includes lint, formatting, types, full Python suite with coverage, all
  portal tests, workflow checks and mirror/ledger validation.
- External-result tests pass in UTC, Pacific/Pago_Pago, Pacific/Auckland and
  Pacific/Kiritimati. `git diff --check` is clean.
- Preserved ignored local browser screenshots while replaying the original commit
  that once tracked them, then restored the local copies after its removal commit.
  No screenshots are present in the PR's final tree.
- Wisdom review: no new behavior, dependencies or backend changes; no prior tests
  modified. Existing spec and plan still describe the resulting implementation.
- Commit: `chore(scoreboard): record external rows rebase validation`. Push the
  rebased branch with a lease pinned to old remote head `f9a9d19ca`.
- No Linear writes or deployment.

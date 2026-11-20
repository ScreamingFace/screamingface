---
ticket: OME-893
stack: repo
status: done
started: 2026-11-18
finished: 2026-11-18
---

# Refresh open PRs and reconcile completed work

## Intent

Filip requested refreshing both remaining PRs, pausing the deprioritized external-results epic, and closing Linear tasks whose PRs merged. Preserve the reviewed provider-credit verification while updating the existing documentation PR with matching task records.

## Planned changes

Refresh #1841 onto main; close both credits-card mirrors and the search-page and weight-label mirrors; finish the two search ledgers; record the external-results epic as Backlog/deferred. Refresh #1749 independently and hold it in draft. No new feature work or merges are authorized by this maintenance request.

## Test plan

Check exact merge evidence and Linear status; inspect the rebased diff; run repository gates. Run scoreboard gates and a desktop/mobile light/dark preview for the refreshed #1749 branch.

## Acceptance

Both existing PRs are current with main, #1749 remains paused, four merged issues are Done in Linear and their repository mirrors, and the verification evidence remains intact.

## Outcome

Both branches are rebased onto main. The source-health test-list conflict retains both suites, and full scoreboard gates pass. Four merged tasks are Done in Linear; repository mirrors and search-page ledgers match. The external-results epic is Backlog/deferred, with unfinished work recorded separately from completed implementation. The provider-credit verification diff is preserved. All repository gates and the diff check pass for these records.

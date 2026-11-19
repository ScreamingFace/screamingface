---
ticket: OME-1309
stack: scoreboard
status: planned
started: 2026-11-18
finished:
---

# External-results work deferred by the owner

## Intent

Filip put E20 on hold on 2026-11-18 because it has been deprioritized. Linear is Backlog with the deferred label. This record covers the unfinished work waiting for reprioritization; completed implementation ledgers retain their original outcomes.

## Planned changes

After the owner resumes the epic: revisit source selection, imports, source-health rollout and live acceptance. PR #1749 is preserved in draft after a maintenance rebase; it must not be merged or deployed as part of this pause.

## Test plan

When resumed, recheck current CI and migration ordering, then perform the explicitly authorized deployment acceptance. No production activity is part of the pause.

## Acceptance

The owner explicitly reprioritizes the epic before remaining feature or rollout work resumes.

## Outcome

Deferred. PRs #1731 and #1729 are merged; broader imports and live acceptance are unfinished. The one-time branch refresh is maintenance requested alongside this pause, not a resumption of the epic.

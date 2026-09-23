---
ticket: OME-1135
stack: screamingface
status: done
started: 2026-09-23
finished: 2026-09-23
---
# Refresh activity Client PR on current main

## Intent

Refresh #983 onto current main after URL4 native iteration indexing merged. Preserve
all existing dynamic activity UI and candidate completion fixes. #988 and #980 are
already current, green and conflict-free; retain #980's stack until #988 merges.

## Planned changes

Rebase existing Client branch, preserving merge resolutions and behavior. Update this
ledger and PR validation. No new UI, protocol, or benchmark changes.

## Test plan

Compare rebased Client tree with previous head, then full screamingface gates and
local HTTP activity smoke against #980. Existing tests remain unchanged.

## Acceptance

Updated draft PR, green local gates, no merge, no ticket status change. Exact existing
Client behavior preserved while inheriting merged URL4 index support.

## Outcome

Rebased with merge history retained onto origin/main 375b6803. Reapplied the prior
widget merge resolution and root-only completion regression coverage. Exact comparison
against previous head bae387de shows no Client source/test changes; only the merged
URL4 index commit is added. This is a dependency refresh, not a behavior change.

#988 and #980 are both OPEN, conflict-free and all CI checks pass. #980 retains its
#988 base because that PR has not merged. No redundant rebase or status changes.

Live HTTP/URL4 IFEval smoke against the local #980 Engine passes: two cases, positions
(1,2)/(2,2), all four activity stages decoded, zero invalid records, no paid calls.
Full Client gates pass: append-only preservation, lint, format, types, full pytest
with 95% coverage threshold, deterministic notebook checks, build and distribution.
No test changes or new behavior. PR remains draft / issue In Progress pending acceptance
and merge. Rebase head 1e1648e8 preserves prior merge intent; this ledger records verification.

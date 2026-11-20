---
id: OME-1967
linear_url: https://linear.app/openmined/issue/OME-1967/simplify-detached-runs-after-p2-ships-drop-the-p1-transition-code-one
status: triage
type: improvement-ideas
priority: low
labels: [improvement-ideas, agentic, deferred]
related: OME-1837
created: 2026-11-18
closed:
---

# Simplify detached Runs after P2 ships: drop the P1 transition code, one Report source, one async Client core

Three cleanups for detached Runs, found while reviewing the E5 P2 PRs (#1759 Engine, #1878
Client). Each removes code that keeps producing review findings; none changes what users get from
P2. **It does not block closing `OME-1837`.**

1. **Remove the P1 transition code from the Engine** (the startless pass and P1's pending grace,
   an older App's flag-only cancel, the P1 exceptions in the driver's queries). It stops mattering
   once 30 days have passed since the first P2 deploy, so it is deleted then, with no downtime.
   Start after: the P2 Engine deploy plus 30 days.
2. **One source for a Run's Report in the Client:** the Engine's records and context, with
   results cached by Run, index and checksum. Changes how `sf.reports` shows P2 Runs; spec first.
   Also ends `reports._downloaded` reading every saved `run.json` to find one Report.
3. **One async Client core,** with the sync Client running it on a background loop. SDK-wide;
   done together with 2. Spec and plan first. Also ends each follow and fetch rule existing
   twice, and the `runtime_checkable` Protocols that pass a sync transport as an async one.

- 2026-11-18: filed as `improvement-ideas` (Triage, unassigned), related to `OME-1837`, after the
  owner deferred these so P2 merges in its current design. Mirrored to GitHub as #1939 by the
  Linear sync.
- 2026-11-18: item 4 added, deferred by the owner from point 6 of a review of #1878.
- 2026-11-18: items 2 and 3 gain three findings from a review of #1878 (the saved-report scan, the
  twins' copied rules, the Protocols that match by name).
- 2026-11-19: item 4 (download results off the follow's frame loop) done in #1878 instead, after a
  re-review held it; removed here.

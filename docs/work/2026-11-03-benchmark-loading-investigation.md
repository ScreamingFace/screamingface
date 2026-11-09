---
ticket: unfiled
stack: scoreboard
status: done
started: 2026-11-03
finished: 2026-11-03
---

# Benchmark homepage loading investigation

## Intent

Investigate the reported slow benchmark loading on the public leaderboard homepage.
Read-only investigation; no application changes, deployment, or external writes.

## Planned changes

Record live browser measurements, trace current-main loading code, and recommend a fix.

## Test plan

Measure real production resource timings and card visibility. Isolate whether one hidden
board can block the first visible page with a browser-only intercepted response.

## Acceptance

Identify a reproduced cause and distinguish measured delays from inferred server costs.

## Outcome

- Inspected main ffdc7e93f and https://leaderboard.screamingface.ai/ on 2026-11-03.
- Live page renders 86 cards but initially displays 9. It issues one catalog request plus
  86 leaderboard requests (`top=1`) on every observed page load.
- First navigation: catalog response ended at 1504 ms; last board response at 3830 ms.
  No card-visibility observer was installed on this first sample.
- Reload 1: catalog response ended at 561 ms (390 ms request duration); cards visible
  at 2084 ms. 86 board requests transferred 161949 bytes including resource-timing overhead.
- Reload 2: catalog response ended at 497 ms (344 ms request duration); cards visible
  at 1938 ms. 86 board requests transferred 161975 bytes including resource-timing overhead.
- Browser-only causal probe: fulfilled 85 leaderboard responses immediately with empty
  entries and held the hidden worldsense response. The DOM had zero cards and the grid
  remained hidden with Loading benchmarks status. Releasing that one response produced
  86 cards, with 9 visible. All interception was removed afterward.
- Source: main.js initIndex awaits Promise.all over every listed board before creating
  any cards. Show more only changes visibility; it does not defer network requests.
- Source: get_leaderboard still reads baselines, ranking, full-board Pareto inputs when
  pinned, member models and pinned caches, and rechecks visibility for top=1. This is
  more work than the single number consumed by the index. Production SQL timings and
  database pool contention were not measured; do not claim they are proven bottlenecks.
- Recommendation: render clickable cards as soon as the catalog arrives, with explicit
  pending score state. Fetch scores only for revealed cards as a narrow first improvement;
  settle failures independently. For the planned scored-only filter, use a bulk catalog
  score summary preserving current ranking/revision/case-count/visibility semantics,
  instead of querying each full leaderboard or filtering only the loaded first page.
- Linear searches for scoreboard slow/performance found no dedicated open loading issue.
  OME-1452 (DB pool sizing) is Done; catalog search/filter work is separate.
- Actual files: this investigation ledger only.
- Commits: none.
- Gates: two observed live reloads and one browser-only causal probe; no code changed.
- Deviations: no production changes or new issue/PR created. Timings are this browser's
  samples, not production-wide percentiles or a promised speedup.

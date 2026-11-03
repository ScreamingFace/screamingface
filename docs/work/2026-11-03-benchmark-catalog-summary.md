---
ticket: OME-1763
stack: scoreboard
status: in_progress
started: 2026-11-03
finished:
---

# Benchmark catalog summary

## Intent

Implement the owner's approved single-response catalog, option C (alphabetical,
Has scores on, search and nine-card Show more), without caching. Coordinate OME-1383.
Measure the old and new loading paths locally against observed production timings.

## Planned changes

- New compact summary schema, bulk SQL projection and route; no migrations.
- Homepage controller, accessible search/filter/count controls, existing card styling.
- New API parity and portal behavior tests; register both in gates/CI.
- Repeatable local performance harness and results with explicit network assumptions.

## Test plan

RED first: missing endpoint and catalog controller. API parity with ranked top=1 for
revision/case-count eligibility, duplicate specs, null revisions, zero/negative/empty
scores, baselines, private boards and visibility changes on SQLite/PostgreSQL. Assert
two queries independent of catalog size and no caching. UI search/filter before paging,
clear/include actions, failure/empty states and no per-board requests. Browser smoke
at mobile/desktop. Run scoreboard/repo gates and production-shaped local measurements.

## Acceptance

One summary request, no per-board requests or caching; existing public score meanings
preserved. Private results excluded. Nine-card batches searchable across the whole
catalog. Baseline reproducible locally, measurements distinguished from projections.

## Outcome

- Implemented compact /v1/benchmarks/summary with grouped score aggregation and a
  final bulk visibility check. Constant two queries, no caches or migrations.
- Implemented alphabetical catalog, default Has scores filter, complete-catalog
  search, include/clear actions, accessible counts and nine-card batches.
- New tests: 16 SQLite/PostgreSQL cases (including a private flip during the read)
  and four DOM-controller tests. Existing tests unchanged.
- Gates: scoreboard and repo ALL GATES GREEN. Full Python suite: 1782 passed,
  64 skipped, 3 deselected; coverage 91.86%. All registered portal tests passed.
- Browser: desktop/mobile, dark mode, filter/query/paging/navigation URL and 503
  state checked; no page errors or mobile overflow. One UI API request throughout.
- Performance: docs/work/2026-11-03-benchmark-catalog-performance.md and its
  versioned evidence. Local 150 ms/request comparison: median 425 ms → 162 ms.
  Production observed 1.8–2.3 s; trace replay reproduces roughly 1.8 s but is NOT
  a deployment forecast. Synthetic 21000-row summary median 27 ms.
- Deviations: an initial one-statement design was expanded to two fixed queries
  to preserve the repository's final visibility recheck. No existing guard was
  weakened. PostgreSQL 15 local; PostgreSQL 17 covered by the CI job.
- Review/merge pending. No deployment. Commits: see git history for this ledger.

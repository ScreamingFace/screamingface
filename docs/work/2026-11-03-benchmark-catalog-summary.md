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

- Implemented compact /v1/benchmarks/summary with a bulk ranked-candidate projection and a
  final bulk visibility check. Constant two queries, no caches or migrations.
- Implemented alphabetical catalog, default Has scores filter, complete-catalog
  search, include/clear actions, accessible counts and nine-card batches.
- API tests: 32 passed across SQLite/PostgreSQL, two PostgreSQL cases skipped
  because its column types reject the corrupt fixture values. Four DOM-controller
  tests pass. Existing tests unchanged; new cases are append-only.
- Gates: scoreboard and repo ALL GATES GREEN after the review fixes, including
  full Python coverage gate, lint, type checking and all registered portal tests.
- Browser: desktop/mobile, dark mode, filter/query/paging/navigation URL and 503
  state checked; no page errors or mobile overflow. One UI API request throughout.
- Performance: docs/work/2026-11-03-benchmark-catalog-performance.md and its
  versioned evidence. Local 150 ms/request comparison: median 439 ms → 162 ms.
  Production observed 1.8–2.3 s; trace replay reproduces roughly 1.8 s but is NOT
  a deployment forecast. Synthetic 21000-row summary median 32 ms.
- Deviations: an initial one-statement design was expanded to two fixed queries
  to preserve the repository's final visibility recheck. No existing guard was
  weakened. PostgreSQL 15 local; PostgreSQL 17 covered by the CI job.
- Review/merge pending. No deployment. Commits: see git history for this ledger.

## Review follow-up — 2026-11-04

Owner requested validation and fixes for corrupt-row isolation and card/board parity.
Plan: reproduce independent corrupt provider/score cases on SQLite and PostgreSQL;
add append-only regressions; preserve two fixed reads by selecting one ranked candidate
per benchmark in bulk and applying the existing row decoder; serve unknown for an
unreadable/non-finite candidate. Re-run parity, privacy, gates and local performance.
Keep option C. Pin PR evidence links to commits and replace copied baseline source
with retrieval from its recorded base commit; retain the reproducible public snapshot.


Result: independent SQLite corruption reproduced the catalog 500 for a text score
and the card/board mismatch for malformed providers. The report's isolated text-score
board-200 claim did not reproduce: that legacy board also fails unless the row is
already dropped for another corrupt field. PostgreSQL NaN/Infinity did not cause a
500 in this app version (serialization returned null), but finite validation now
handles them explicitly before response construction. PostgreSQL provider JSON
with the wrong shape is also isolated by the summary.

The fix uses the same provider field decoder as ranking, plus finite-score and
provider-shape validation. Window selection preserves newest-per-spec and
first-claim-between-specs ties. A bad selected candidate logs a warning and returns
null without promoting a lower row; optional corrupt cost/authors fields do not
hide the score. Regression tests cover these cases on fresh fixtures. The scope
and private-flip tests, two-query assertions, full gates and browser smoke pass.

Removed the copied baseline HTML/JavaScript; the harness now reads the immutable
base commit. Kept the small public snapshot and screenshots as reproducible review
evidence, rather than moving them to unversioned attachments. PR links are pinned
to a commit. Alphabetical/default-scored option C remains the approved behavior.
Performance was remeasured and the report/evidence updated; no cache was introduced.

## Publication review — 2026-11-05

Owner requested a final review and publication if sound. Rebase onto current main,
retaining its updated homepage layout and all PostgreSQL CI registrations. Review
score eligibility/tie selection, corruption isolation, privacy exit checks, static
route integration, DOM safety, search/filter/paging and failure states. Run full
scoreboard/repository gates, the combined PostgreSQL CI selection, and browser
smoke on desktop/mobile/dark layouts before publishing the existing draft PR.

Outcome: no blocking findings. Rebased on `0b2d63facecc9fe44924dda7573cf84a8021ac42`.
The only conflict was the PostgreSQL workflow selection; retained every existing
suite plus the catalog suite. Range-diff confirms the corruption fix is unchanged;
main's current homepage layout/copy is preserved. No application behavior changes
were needed during this review.

Full scoreboard and repository gates pass. The workflow's complete PostgreSQL
selection passes: 245 tests, two expected skips for corruption PostgreSQL rejects
on write. Browser smoke passes for one request, nine-card paging, search beyond the
first page, filter/clear/include actions, empty/error states and responsive layouts.
Refreshed desktop/mobile/dark screenshots; dark mode is now exercised through the
actual theme button. No cache or fallback request fan-out was added. The recorded
performance comparison remains the 2026-11-04 measurement; production speedup still
requires measurement after deployment. Ready to publish for external review; not
merged or deployed by this task.

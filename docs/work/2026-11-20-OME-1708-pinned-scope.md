---
ticket: OME-1708
stack: scoreboard
status: in_progress
started: 2026-11-20
finished:
---

# Preserve pinned revision scope and actual submission presence

## Intent

Fix the two additional P2 findings in Dmitry's review of PR #1943, as requested by Filip. An explicit revision remains pinned across a concurrent benchmark update; imported top-50 rows cannot make an existing community cohort appear empty.

## Planned changes

- Keep a valid URL revision on board and frontier requests, even if the list calls it current. Preserve dynamic Latest for an absent parameter or explicit Latest selection.
- Track community submission presence before merging/truncating imported references.
- Extend the real-script integration tests for the revision race and displaced community rows, preserving the earlier fixes.

## Test plan

Demonstrate both failures in regression tests before editing production code. Check explicit Latest selection, both list/board response orders, and reset to an empty historical revision. Run full scoreboard/repository gates and inspect local desktop/mobile light/dark previews before pushing.

## Acceptance

The URL, board request and frontier request retain the explicit revision through a concurrent bump. A fetched community submission prevents the false no-submissions message even if all 50 displayed rows are imported. Genuine empty cohorts retain their messages. All checks pass.

## Outcome

Both fixes are implemented in `portal/benchmark.js`: valid explicit URL revisions pass through to both reads, and `hasSubmissions` is captured before imported-row selection. The integration suite adds a pinned-current race case with explicit Latest selection and two displaced-community cases covering both response orders and reset to an empty historical revision.

All three new cases failed before the fixes. All 33 focused tests pass afterward; full scoreboard gates, repository gates and diff checks pass against main `f7153ee5e`. The rebase was clean. Existing tests remain intact.

Headless Chromium used the real local board/frontier APIs with fixture data and a controlled old revision-list snapshot. Both requests retained A; its score stayed 0.4 while current C was already 0.9. Choosing a historical revision then Latest removed the URL parameter and returned C's 0.9. A real API response with one community entry and 50 eligible imports rendered all 50 references without a false empty message. Desktop 1440px/mobile 390px in light/dark show no page-wide overflow or JavaScript errors. Existing long-benchmark breadcrumb crowding on mobile is unchanged. Preview: http://127.0.0.1:9202/benchmarks/review-pin/?revision=aaaaaaaa and http://127.0.0.1:9202/benchmarks/inspect-agieval_sat_en/.

PR #1943 remains open for review. No API, schema or production changes.

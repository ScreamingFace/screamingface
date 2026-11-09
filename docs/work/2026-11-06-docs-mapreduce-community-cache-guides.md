---
ticket: OME-1842
stack: repo
status: in_progress
started: 2026-11-06
finished:
---

# docs-mapreduce-community-cache-guides — SF Client docs: map-reduce + community-cache guides and compose polish

## Intent

Follow-up documentation work on the SF Client docs (`public-docs`), stacked on the OME-426
docs branch (PR #1436). Adds two new How-to guides and polishes the Compose section so the
docs read clearly and stop asserting an inaccurate local-engine limitation.

## Changes

- **New** `public-docs/src/pages/sf-client/guides/MapReducePage.vue` — "Map-reduce for
  fusions": the dispatch → map → filter → reduce stages, signals (extracted / judge / engine),
  worked examples, and two inline SVG diagrams. Wired into router + nav (Compose group).
- **New** `public-docs/src/pages/sf-client/guides/CommunityCachePage.vue` — "Use the
  community's cache": the `sf.cache.pull_from_remote` flow for local engines. Wired into
  router + nav (How-to guides).
- Restructure the leaderboards "Publish a result" section into labelled bullets
  (`guides/LeaderboardsPage.vue`).
- Retitle Fusions → "Fanout fusion" and trim its repeated reducer prose
  (`guides/FusionsPage.vue`, `navigation/sf-client.ts`).
- Retitle the DRACO quickstart → "Reproduce OpenRouter's DRACO results"
  (`QuickstartPage.vue`, `navigation/sf-client.ts`).
- Reframe the "local engine serves only medxpert" claim across the SF Client docs
  (FirstFusion, Installation, api/Benchmarks, api/CandidateResult, guides/Benchmarks,
  guides/Evaluation, learn/Engine).
- HomePage hero lead tightened; Compose nav group reordered.

## Acceptance

- Both new guides render; `npm run type-check` passes; routes return 200.
- No em-dashes in the edited/new pages.
- No remaining "serves only medxpert" restriction claims.

## Outcome (fill at the end)

- **Actual files:** as above (15 files; 2 new).
- **Commits:** 89c674273 — docs(public-docs): add map-reduce + community-cache guides and polish compose docs
- **Gates:** `vue-tsc --noEmit` clean; dev server routes 200 (no automated test suite in public-docs).
- **Deviations:** none.

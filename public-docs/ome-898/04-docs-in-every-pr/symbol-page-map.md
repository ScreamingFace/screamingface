---
title: "Documentation as part of every PR: the symbol-to-page table"
ticket: OME-898 (child 4, not yet filed)
spec: ./spec.md
plan: ./plan.md
status: draft
date: 2026-09-17
---

# The symbol-to-page table

Plan step 1. Maps every name in `packages/screamingface/src/screamingface/__init__.py`'s
`__all__` (58 entries) to the `public-docs/src/pages/sf-client/api/*.vue` page that
documents it. Built by checking, for each name, which pages mention it, then choosing the
page whose title matches its class family. This is what the check script in step 2 reads.

## Three symbols with no page at all

Independent of the CI check itself:

| Symbol | What it is |
|---|---|
| `__version__` | the installed distribution's version |
| `OperationAccounting` | exported, not referenced anywhere in `public-docs/` |
| `OperationCache` | exported, not referenced anywhere in `public-docs/` |

These need a page, or an explicit decision that they are exempt (a version string might
reasonably not need one; the other two look like a real gap). The check in step 2 cannot
require a page for these until one is assigned, so for now they are excluded from
enforcement rather than silently ignored.

## The table

| Symbol | Page |
|---|---|
| `Client` | `ClientsPage.vue` |
| `AsyncClient` | `ClientsPage.vue` |
| `Recipe` | `RecipesPage.vue` |
| `CorrectiveLoop` | `RecipesPage.vue` |
| `SelfCorrective` | `RecipesPage.vue` |
| `Model` | `ModelsCatalogPage.vue` |
| `ModelCapability` | `ModelsCatalogPage.vue` |
| `ModelDetails` | `ModelsCatalogPage.vue` |
| `ModelInfo` | `ModelsCatalogPage.vue` |
| `ModelParameter` | `ModelsCatalogPage.vue` |
| `ModelParameterSchema` | `ModelsCatalogPage.vue` |
| `Fusion` | `FusionsPage.vue` |
| `Pipeline` | `PipelinesPage.vue` |
| `Url4` | `Url4Page.vue` |
| `Benchmark` | `BenchmarksPage.vue` |
| `Connection` | `ConnectionsPage.vue` |
| `ConnectionPanel` | `ConnectionsPage.vue` |
| `AsyncOAuthFlow` | `ConnectionsPage.vue` |
| `OAuthFlow` | `ConnectionsPage.vue` |
| `connect` | `ConnectionsPage.vue` |
| `disconnect` | `ConnectionsPage.vue` |
| `connections` | `ConnectionsPage.vue` |
| `Report` | `ReportsPage.vue` |
| `CandidateResult` | `CandidateResultPage.vue` |
| `BenchmarkInfo` | `CandidateResultPage.vue` |
| `CaseGrade` | `CandidateResultPage.vue` |
| `CaseResult` | `CandidateResultPage.vue` |
| `Check` | `CandidateResultPage.vue` |
| `Evidence` | `CandidateResultPage.vue` |
| `EvidenceProducer` | `CandidateResultPage.vue` |
| `Failure` | `CandidateResultPage.vue` |
| `MemberResult` | `CandidateResultPage.vue` |
| `OperationInfo` | `CandidateResultPage.vue` |
| `Usage` | `UsagePage.vue` |
| `Leaderboard` | `LeaderboardsPage.vue` |
| `LeaderboardBaseline` | `LeaderboardsPage.vue` |
| `LeaderboardEntry` | `LeaderboardsPage.vue` |
| `LeaderboardInfo` | `LeaderboardsPage.vue` |
| `LeaderboardScore` | `LeaderboardsPage.vue` |
| `leaderboards` | `LeaderboardsPage.vue` |
| `Event` | `EventsPage.vue` |
| `events` | `EventsPage.vue` |
| `AuthenticationError` | `ErrorsPage.vue` |
| `EngineUnavailableError` | `ErrorsPage.vue` |
| `ExecutionError` | `ErrorsPage.vue` |
| `EvaluationWarning` | `ErrorsPage.vue` |
| `LeaderboardError` | `ErrorsPage.vue` |
| `PlanningError` | `ErrorsPage.vue` |
| `ProviderConnectionError` | `ErrorsPage.vue` |
| `ScreamingFaceError` | `ErrorsPage.vue` |
| `configure` | `ModulesPage.vue` |
| `close` | `ModulesPage.vue` |
| `evaluate` | `ModulesPage.vue` |
| `benchmarks` | `ModulesPage.vue` |
| `models` | `ModulesPage.vue` |

55 of 58 names assigned. The three gaps are listed above, not in the table.

## Keeping this current

The symbol list and its source files are re-derived from `__init__.py` on every run (see
`scripts/check_docs_sync.py`), so most code changes need no edit here. Two things do need a
manual update to this table, and the script is built to fail rather than pass silently in
both cases: a name newly added to `__all__` has no entry yet, so the check fails and names
the exact fix; a page that gets renamed is not detected automatically, so the check fails as
a false positive (reporting no docs change when one did happen, under a new filename) rather
than as a false pass.

## How this was built

For each of the 58 names, `grep -lw` across the 15 API reference pages found every page that
mentions it. Most names are mentioned on several pages, since a `Fusion` example references
`Model` and `Recipe` in prose. The table above picks the one page whose title matches the
symbol's class family, following the same grouping `sfClientReferenceNavigation` already
uses for its sidebar sections. `ModulesPage.vue` is the assigned home only for the top-level
`sf.*` functions and sub-modules that have no more specific page of their own; it is not a
catch-all for anything that happens to mention a name in passing.

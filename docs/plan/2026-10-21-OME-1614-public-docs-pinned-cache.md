# OME-1614 plan — public docs for pinned-cache replays and metadata

Implementation authorized 2026-10-22. Spec: `docs/spec/2026-10-21-OME-1614-public-docs-pinned-cache.md`. Branch
`OME-1614-public-docs-pinned-cache` on `origin/main`. One draft PR; implementation groups:

| # | Group | Files |
|---|---|---|
| 1 | Concept pages | `learn/CachingPage.vue`, `learn/LeaderboardPage.vue`, `CONTEXT.md` |
| 2 | Leaderboards guide | `sf-client/guides/LeaderboardsPage.vue` (reproduce section, metadata, upgrade note) |
| 3 | Other guides | `sf-client/guides/EvaluationPage.vue`, `sf-client/guides/Url4Page.vue` |
| 4 | API reference | `sf-client/api/ClientsPage.vue`, `ModulesPage.vue`, `CandidateResultPage.vue`, `LeaderboardsPage.vue`, `ErrorsPage.vue`; `navigation/sf-client.ts` source baseline |
| 5 | Snippet check and ledger | a scratch script checks the changed replay/metadata snippets against the #1519 SDK; outcome in the ledger |

Validate the final content with `npm run build`, `npm run lint`, offline SDK snippet checks,
the repository gates, and browser checks in light/dark themes. Commit as one coherent docs update.
Before un-drafting: re-run the snippet check
against PyPI 0.1.7. Out of scope: any SDK, scoreboard or Engine change; pages that do not mention
E14 today.

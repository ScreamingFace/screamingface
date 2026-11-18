---
ticket: unfiled   # slug-named ledger; backfill to OME-N at PR-open
stack: repo
status: in_progress
started: 2026-11-18
finished:
---

# public-docs-e4c-cascades-gates — bring the public docs site current with the merged E4c cascades/gates/budgets work

## Intent

PR #1733 (E4c, epic OME-1291, merged 2026-11-13) made `sf.Gate` the single branch construct and
added `sf.Cascade`, selectors (`sf.RegexClassifier`/`sf.LLMClassifier`), guards, typed outcomes
(`sf.abstain()`/`sf.fail()`) and per-Case budgets (`sf.WithBudget`). It updated the SDK package docs
(README, CHANGELOG, notebook 20) but NOT the public docs site (`public-docs/`, docs.screamingface.ai).
Those pages are still pre-E4c and now wrong — `ReducersPage.vue` literally says
`sf.Gate then= takes sf.Vote until E4c`. Bring them current, ported from the already-correct SDK
README + spec PRDs, verified against SDK source.

## Planned changes

- `public-docs/src/pages/sf-client/api/ReducersPage.vue` — rewrite the Gate section (widen
  then=/otherwise=, typed sf.abstain()/sf.fail(), lazy recipe otherwise, update abstain-reason list).
- THREE new pages (split on user direction — routing is not yet shipped as a product surface):
  - `CascadesGatesPage.vue` — cascades + gates (shipped).
  - `BudgetedRunsPage.vue` — per-case budgets (shipped).
  - `RoutersPage.vue` — "coming soon" placeholder (classifiers, guards, set-valued routing).
- `public-docs/src/pages/sf-client/api/ErrorsPage.vue` — add CascadeSeedWarning to hierarchy + table
  (fail_closed/signal_missing/budget_refused documented on the cascades/budget pages, not Errors —
  they are case reasons, not Client exceptions).
- `public-docs/src/navigation/sf-client.ts` + `public-docs/src/router/index.ts` + `public-docs/CLAUDE.md`
  — wire the three new pages.

## Test plan

- No unit-test harness in public-docs. Gates: `npm run type-check`, `npm run lint`, `npm run build`.
- Every code sample verified by construction against the SDK source
  (`packages/screamingface/src` + `packages/url4/src` on sys.path) before it goes in the page.

## Acceptance

- `ReducersPage` no longer contains the `until E4c` restriction; typed outcomes + new failure codes
  are documented.
- A page covers `sf.Cascade`, `sf.escalate_if`, `sf.RegexClassifier`/`sf.LLMClassifier`, guards and
  `sf.WithBudget` with examples that build on the current SDK.
- Errors page lists the three new failure codes.
- type-check + lint + build all clean.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** ReducersPage.vue (edited), ErrorsPage.vue (edited), CascadesGatesPage.vue (new),
  BudgetedRunsPage.vue (new), RoutersPage.vue (new, coming-soon), navigation/sf-client.ts,
  router/index.ts, public-docs/CLAUDE.md.
- **Commits:** (pending — not committed yet; awaiting user review before PR-open under OME-1291)
- **Gates:** `npm run type-check` clean, `npm run lint` clean, `npm run build` ✓ (all three new pages
  emit assets). Every code sample verified by construction against the SDK source.
- **Deviations:** Split the single planned page into three (cascades/gates, budgeted-runs, routers)
  per user direction that routing is not yet a shipped surface — routers page is a placeholder. Caught
  and fixed one inaccurate sample: the `sf.abstain()`-closed cascade equals a gate with an EXPLICIT
  `otherwise=sf.abstain()`, not the default-otherwise gate.

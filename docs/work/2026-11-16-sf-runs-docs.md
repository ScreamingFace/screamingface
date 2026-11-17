---
ticket: OME-1936
stack: public-docs
status: done
started: 2026-11-16
finished: 2026-11-17
---

# sf-runs-docs — document sf.runs + a "Managing experiments" guide

## Intent

E5 P1 shipped the `sf.runs` module in the Client SDK (`d63c353a7c`), but the docs site had no
page for it and no guide teaching the workflow it unlocks. This unit adds both, following the
site's Divio split: a reference page for `sf.runs` and a how-to guide for managing experiments
(runs) across the hosted engine or a researcher's own stack.

## Planned changes

- `public-docs/src/pages/sf-client/api/RunsPage.vue` (new) — `sf.runs` reference.
- `public-docs/src/pages/sf-client/guides/ExperimentsPage.vue` (new) — how-to guide.
- `public-docs/src/router/index.ts` — two routes.
- `public-docs/src/navigation/sf-client.ts` — nav entries (Run under Results & grading;
  Manage experiments under How-to guides).
- `public-docs/src/pages/sf-client/api/ModulesPage.vue` — add `sf.runs` to the namespace list + section.
- `public-docs/src/pages/sf-client/guides/EvaluationPage.vue` — see-also cross-link.
- `public-docs/CLAUDE.md` — route table.

## Test plan

- Docs site has no automated test suite. Gates: `npm run type-check`, `npm run lint`,
  `npm run build` must pass; both routes must render under `DocLayout` and appear in the
  correct sidebar group with working prev/next.
- Content cross-checked against `packages/screamingface/src/screamingface/runs.py` and the eng
  "Find and manage your Runs" notebook.

## Acceptance

- `/sf-client/api/runs` and `/sf-client/guides/managing-experiments` render and are wired into
  the sidebar.
- Prose matches house style (no em dashes; casing: Client / engine / url4 / leaderboard).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (2 new pages + 5 edits).
- **Commits:** 77194c409 — docs(public-docs): add sf.runs reference and a Managing experiments guide
- **Gates:** `npm run type-check` ✓ · `npm run lint` ✓ · `npm run build` ✓.
- **Deviations:** none.

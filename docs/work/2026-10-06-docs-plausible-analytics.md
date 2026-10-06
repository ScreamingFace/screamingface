---
ticket: OME-1505
stack: repo
status: in_progress
started: 2026-10-06
finished:
---

# docs-plausible-analytics — Plausible analytics on docs.screamingface.ai

## Intent

docs.screamingface.ai shipped with no analytics, so there is no view of which docs pages are
read, where readers come from, or which snippets they copy. This adds OpenMined's Plausible
(cookieless, no consent banner) to `public-docs`, on the site `docs.screamingface.ai` in the
OpenMined Plausible account, configured like the screamingface.ai site.

## Planned changes

- `public-docs/index.html`: the Plausible site snippet in `<head>`.
- `public-docs/src/lib/analytics.ts` (new): `track`, `trackNotFound`, `trackCodeCopy`.
- `public-docs/src/pages/NotFoundPage.vue`: report `404` with the missed path on mount.
- `public-docs/src/composables/useCopy.ts`, `src/components/ui/NotebookViewer.vue`: report
  `Code Copy` with the page path after a successful copy.
- `public-docs/CLAUDE.md`: list `analytics.ts` under `src/lib/`.

## Test plan

- `public-docs` has no test runner (see `public-docs-tests.yml`); the gate is lint + build.
- Manual, against `vite preview` with plausible.io blocked so the snippet's queue is readable:
  an unknown route queues `404` with its path; a copy button queues `Code Copy` with its path.

## Acceptance

- Production pageviews appear on the Plausible site, including client-side navigations.
- An unknown URL records a `404` event; a copy click records `Code Copy`.
- Nothing is sent from localhost; a blocked script causes no console error.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see PR.
- **Gates:** `npm run build` (type-check + vite build) pass; `oxlint` and `eslint` clean;
  `prettier --check` clean on the touched `src/` files.
- **Deviations:** no spec or plan artifact (small, urgent change; scope and acceptance live in
  OME-1505 under E12 / OME-1305). The `Code Copy` goal still has to be added on the Plausible site
  for that event to show in the dashboard; `404` and the automatic goals already exist.

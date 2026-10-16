---
ticket: OME-426
stack: repo
status: done
started: 2026-10-15
finished: 2026-10-16
---

# docs-align-sf-client-0-1-3 — Align the SF Client docs with screamingface 0.1.3

Epic: `OME-426` (Docs polish pass, launch).

## Intent

Fix drift between the SF Client docs (`public-docs`) and screamingface 0.1.3, the released package. Every statement, sample and number on the affected pages is verified against 0.1.3 on a local engine, and on the hosted engine where the account allows. The team's answers to the open questions decide which side is right.

## Planned changes

- `public-docs/src/pages/sf-client/**` and `public-docs/src/pages/learn/**`: correct false claims, samples and numbers; split local and hosted content into separate sections where behaviour differs; switch dev hosts to production; remove slash benchmark ids, `sf.reproduce`, `hle` and the `draco-lite` link.
- `public-docs/src/lib/engine.ts`: production engine URL.
- `public-docs/src/navigation/sf-client.ts`: footer states the version the docs were written against (0.1.3).
- New or extended reference pages for the 0.1.3 surface that no page documents: reducers and blocks, `Fusion(quorum=, optional=)`, `sf.reports`, `save_results`, accounting and trace members.
- Exact file list is fixed in `docs/spec/` before implementation.

## Test plan

- `public-docs` has no test suite. Gates: `npm run type-check`, `npm run lint`, `npm run build`.
- Every code sample on an edited page runs against a fresh 0.1.3 install (local engine; hosted where the account allows) and its printed output is reprinted from the run.
- Every number, id, count and revision on an edited page is re-read from a live 0.1.3 call.
- Link check over the built site: every internal route resolves and every external link answers 200.
- Each edited page is reread for accuracy against 0.1.3 and plain wording.

## Acceptance

- No page states a dev host as a default.
- No page lists a slash benchmark id, `sf.reproduce`, `hle` or the `draco-lite` link.
- Each page that differs between local and hosted has a section for each.
- Every sample on an edited page was run on 0.1.3 and matches the printed output.
- The footer names 0.1.3.
- Type-check, lint and build pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `public-docs/src` (35 files), `public-docs/vite.config.ts`, `public-docs/env.d.ts`, `public-docs/CLAUDE.md`, `.github/workflows/deploy-public-docs.yml`, `docs/spec`, `docs/plan`, `docs/work`, `docs/tasks`.
- **Commits:** `001addd2b` to `2eccc9298` (11), plus the ledger and task mirror.
- **Gates:** type-check, lint and build pass. 38 internal and 13 external links resolve.
- **Deviations:** Spec gained D20. Footer version comes from the release tag, and the deploy job fetches full git history to find it.

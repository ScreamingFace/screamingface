---
ticket: OME-426
stack: repo
status: in_progress
started: 2026-10-15
finished:
---

# docs-align-sf-client-0-1-9: Align the SF Client docs with screamingface 0.1.9

Epic: `OME-426` (Docs polish pass, launch).

## Intent

Fix drift between the SF Client docs (`public-docs`) and screamingface 0.1.9, the released package. Every statement, sample and number on the affected pages is verified against 0.1.9 on a local engine, and on the hosted engine where the account allows. The team's answers to the open questions decide which side is right. The pass follows the OME-898 rules for writing, terminology, claims and review, restated in the spec.

## Planned changes

- `public-docs/src/pages/sf-client/**` and `public-docs/src/pages/learn/**`: correct false claims, samples and numbers; split local and hosted content into separate sections where behaviour differs; switch dev hosts to production; remove slash benchmark ids, `sf.reproduce`, `hle` and the `draco-lite` link; state that capture is off unless `capture=True`.
- `public-docs/src/lib/engine.ts`: production engine URL.
- `public-docs/src/navigation/sf-client.ts`: footer reads the release tag.
- New or extended reference pages for the 0.1.9 surface: reducers and blocks including `sf.Mean`, `Fusion(quorum=, optional=)`, `sf.reports`, `sf.cache`, `sf.analytics`, `sf.classify`, case media, accounting and trace members.
- Diagram sources, SVG and PNG in `docs/diagrams/`.
- Exact file list is fixed in `docs/spec/` before implementation.

## Test plan

- `public-docs` has no test suite. Gates: `npm run type-check`, `npm run lint`, `npm run build`.
- Every code sample on an edited page runs against a fresh 0.1.9 install (local engine; hosted where the account allows) and its printed output is reprinted from the run.
- Every number, id, count and revision on an edited page is re-read from a live 0.1.9 call.
- Every cost claim is measured on a run or removed.
- Link check over the built site: every internal route resolves and every external link answers 200.
- Review report: three passes, nine-item scorecard with quoted evidence, trust check.

## Acceptance

- No page states a dev host as a default.
- No page lists a slash benchmark id, `sf.reproduce`, `hle` or the `draco-lite` link.
- No page states that capture is on by default.
- Each page that differs between local and hosted has a section for each.
- Every sample on an edited page was run on 0.1.9 and matches the printed output, or is marked unverified with the reason.
- Every name in the 0.1.9 `__all__` has a page, or is a listed named exception.
- No page documents a name that is not in the 0.1.9 `__all__`.
- Every diagram in the spec's Diagram plan exists as source, SVG and PNG.
- The review report exists, in the required order.
- No edited page contains an em-dash, and no heading is in title case.
- The footer names 0.1.9.
- Type-check, lint and build pass.

## Outcome (fill at the end, required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

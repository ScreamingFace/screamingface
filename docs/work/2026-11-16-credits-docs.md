---
ticket: OME-1937
stack: public-docs
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-16
finished:
---

# credits-docs — document E5 P3 provider credit visibility on the docs site

## Intent

E5 P3 (provider credit visibility, epic OME-1294, PR #1753 by Filip Boltuzic) shipped
`sf.credits()` / `Client.credits()`, the notebook credit card and the run-start zero notice, but
`docs.screamingface.ai` (the `public-docs/` Vue app) has no credits documentation. This unit adds a
Credits API reference page and a referenceable how-to heading in the Connections guide so users can
discover and use the feature.

## Planned changes

- `public-docs/src/pages/sf-client/api/CreditsPage.vue` — new API reference page (credits(),
  CreditStatus, CreditAmount, states, reasons, management key, hosted vs BYOK).
- `public-docs/src/router/index.ts` — route `/sf-client/api/credits`.
- `public-docs/src/navigation/sf-client.ts` — nav link under API reference → Classes, after
  Connections.
- `public-docs/src/pages/sf-client/guides/ConnectionsPage.vue` — new `See your provider credit`
  section (anchor `#see-your-provider-credit`) + a Links bullet.

## Test plan

- No automated tests in public-docs. Gates: `npm run type-check`, `npm run lint`, `npm run build`.
- Manual: `npm run dev` → the Credits page renders and sits in the sidebar after Connections;
  prev/next steps through it; `/sf-client/guides/connections#see-your-provider-credit` scrolls to the
  new heading; cross-links between the guide section and the API page both resolve.

## Acceptance

- Credits API page reachable, in the sidebar, cross-checked field-by-field against
  `packages/screamingface/src/screamingface/credit.py` and `.../client.py`.
- Connections guide has a linkable `See your provider credit` section.
- type-check + lint + build green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — new `public-docs/src/pages/sf-client/api/CreditsPage.vue`;
  edited `public-docs/src/router/index.ts`, `public-docs/src/navigation/sf-client.ts`,
  `public-docs/src/pages/sf-client/guides/ConnectionsPage.vue`.
- **Commits:** <sha — message> (at PR-open); ticket OME-1937, parent epic OME-1294.
- **Gates:** `npm run type-check` clean; `npm run lint` clean; `npm run build` green (CreditsPage
  chunk emitted). `npm run format` was reverted on files outside this unit to keep the diff scoped.
- **Deviations:** none. Content cross-checked against `credit.py` / `client.py`.

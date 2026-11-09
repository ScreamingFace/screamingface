---
ticket: OME-1676
stack: repo
status: in_progress
started: 2026-10-19
finished:
---

# docs-og-image — link-preview card and canonical URLs on docs.screamingface.ai

## Intent

Shared docs links unfurl on X, Slack and LinkedIn as a small text card with a placeholder icon:
`index.html` has no `og:image`, `twitter:card` is `summary`, and `og:url` and the canonical
link both name `https://screamingface.ai/`, which now redirects to the leaderboard.

## Changes

- `public-docs/public/social/sf-docs-og-1200x630.png` (new): the docs link card, the 😱 mark
  above the ScreamingFace wordmark with the `DOCS` label, as in the navbar. Rendered from the
  brand guide's mark and wordmark files; `PROVENANCE.md` beside it records the inputs.
- `public-docs/index.html`: `og:image` (+ size, alt), `twitter:image`, `twitter:card`
  `summary_large_image`. Static `og:url` and canonical removed: every route serves this file,
  so a fixed value collapses each shared docs link onto one page (same issue as #1443 review).
- `public-docs/src/router/index.ts`: `afterEach` sets the canonical to
  `https://docs.screamingface.ai<path>` for the current route.

## Test plan

- `public-docs` has no test runner; the gate is oxlint + eslint + `npm run build`.
- Against `vite preview`: the card is served at `/social/sf-docs-og-1200x630.png` as
  `image/png`; the rendered DOM's canonical is the docs URL of `/` and of a deep route.
- Visual: the card at full size and centre-cropped to a square keeps the whole lockup.

## Acceptance

- A newly shared docs link shows the card on X and Slack.
- Any docs page's canonical names that page on docs.screamingface.ai.

## Outcome (fill at the end — required before COMMIT)

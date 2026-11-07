---
ticket: OME-1849
stack: repo
status: in_progress
started: 2026-11-06
finished:
---

# docs-request-architecture-diagram — unify and clarify the SF Client docs diagrams

## Intent

Remake the SF Client docs diagrams in one clean, un-branded visual language (sans font, soft
rounded boxes, blue lead box, green/red semantics), replacing the branded IBM Plex Mono / gold
style, and add a few clarifying diagrams. Stacked on OME-1842 (the community-cache guide lives
there).

## Changes

- **New base diagram** `sf-request-architecture-local-{light,dark}.svg`: you → Client → engine →
  gateway → provider; the cache accumulates and pulls from the global cache; a verifiable
  submission goes to the public leaderboard. Wired into the SF Client landing (`Index.vue`),
  replacing the previous local-flow figure.
- **Two focused cuts:** `sf-community-cache-pull-*` (on the community-cache guide) and
  `sf-verifiable-submission-*` (on the learn Leaderboard page).
- **Two map-reduce guide diagrams:** `sf-mapreduce-spine-*` (map → enrich → narrow → reduce) and
  `sf-signal-two-ways-*` (one signal, narrow vs weigh), replacing the two inline SVGs in
  `MapReducePage.vue` (now via `ThemedDiagram`).
- **Reskin the six sf-client-0-1-11-*** diagrams to the same minimal style: strip the in-SVG
  title/subtitle/footnote chrome (the diagram title is the page heading; the detail lives in the
  `ThemedDiagram` caption and prose), sans font, rounded boxes, green-tint success boxes, blue
  lead box in the flow/sequence diagrams.
- **Redesign** `sf-client-0-1-11-pinned-cache-states-*`: a clean success spine (Opening → Open →
  Sealing → Sealed → complete) with the partial-capture reasons listed beside one `partial` box,
  replacing the previous tangle of crossing red arrows.

## Acceptance

- Every diagram renders (rsvg-convert) and is well-formed; `npm run type-check` passes; all
  affected routes return 200.
- The 0-1-11 diagrams match the architecture/submission style (no in-SVG title/subtitle/footnote).
- No em-dashes; light + dark pairs for every diagram.

## Outcome (fill at the end)

- **Actual files:** 6 new SVGs (base + 2 cuts + 2 map-reduce), 12 reskinned/redesigned 0-1-11
  SVGs, plus `Index.vue`, `MapReducePage.vue`, `CommunityCachePage.vue`, `LeaderboardPage.vue`.
- **Commits:** 639eee20a (base + cuts + first reskin), + this batch.
- **Gates:** `vue-tsc --noEmit` clean; all diagrams render; routes 200 (no automated test suite in public-docs).
- **Deviations:** none.

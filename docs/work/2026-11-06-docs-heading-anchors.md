---
ticket: OME-1850
stack: repo
status: in_progress
started: 2026-11-06
finished:
---

# docs-heading-anchors — deep-linkable section headings

## Intent

Let readers reference a specific section of a docs page by URL. Independent of the docs-content
work; touches only the shared DocLayout.

## Changes

- `public-docs/src/components/layout/DocLayout.vue`: after the content mounts, slugify every
  prose heading (h2/h3/h4) into a stable `id` (author-set ids kept), append a hover `#` anchor,
  and scroll the URL hash into view (with `scroll-margin-top` below the sticky navbar) on load and
  on hash change.

## Acceptance

- Headings carry stable ids and a hover `#` anchor; `#id` URLs land on the section below the navbar.
- `npm run type-check` passes.

## Outcome (fill at the end)

- **Actual files:** `DocLayout.vue`.
- **Commits:** 65654377d — feat(public-docs): deep-linkable section headings.
- **Gates:** `vue-tsc --noEmit` clean (verified in the dev worktree on the identical change).
- **Deviations:** scroll-to-section could not be visually asserted in the headless tool (virtual-time
  does not drive scrollIntoView); logic is the standard pattern, confirmed id/anchor DOM output.

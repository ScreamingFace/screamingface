---
ticket: OME-1862
stack: repo
status: in_progress
started: 2026-11-10
finished:
---

# fusions-guide-partial-failures — Fusions guide: handle partial grading failures

## Intent

The SF Client **Fusions guide** (`public-docs`) teaches `sf.Fanout >> sf.Synthesize` but only
mentions quorum/optional as a single buried sentence, while the API reference already renders
the concept with a diagram. A guide reader has no worked, diagrammed explanation of how to
**handle partial grading failures** — that `quorum` on `sf.Fanout` sets how many members must
succeed, and a member built with `optional=True` may fail without stopping the fusion. This unit
adds that as a dedicated section before the `sf.Fusion` shortcut, with a runnable example and the
existing quorum diagram.

## Planned changes

- `public-docs/src/pages/sf-client/guides/FusionsPage.vue`:
  - Import `ThemedDiagram`.
  - Add `quorum`/`quorumOut` example consts (output is the real `repr()` from the local SDK).
  - Fold the one-line quorum mention from "3 · Choose the synthesizer" into a new
    `5 · Handle partial grading failures` section (quorum + `optional=True`, example, diagram),
    placed before the shortcut; renumber the shortcut to `6`.

## Test plan

- `npm run type-check` — Vue SFC + props valid.
- `npm run build` — Vite build compiles `FusionsPage`.
- `npm run lint` — oxlint + eslint clean.
- Visual: new section renders before the shortcut, quorum diagram shows (light/dark), headings
  read 1→6 with no duplicate "5".

## Acceptance

- Guide has a dedicated partial-grading-failures section with example + diagram before the
  `sf.Fusion` shortcut; no duplicated quorum one-liner; build/type-check/lint green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `public-docs/src/pages/sf-client/guides/FusionsPage.vue` (as planned).
- **Commits:** <sha — message>
- **Gates:** type-check ✅ · build ✅ (FusionsPage compiled) · lint ✅.
- **Deviations:** none. Diagram assets + `docs/diagrams` mirror already on `origin/main`; no
  file-add needed (pull brought them in).

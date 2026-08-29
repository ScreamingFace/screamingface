---
ticket: OME-666
stack: public-docs
status: in_progress
started: 2026-08-06
finished:
---

# OME-666 — Re-skin public-docs to SFDS v2 + rewrite the landing as a documentation page

## Intent

The `public-docs` site shipped a product-marketing landing (invented metrics, Product Hunt
badges, "Open Studio" CTAs, rainbow gradients) on a theme that violates the ScreamingFace
Design System (purple primary, Rubik/Bricolage fonts, rounded corners, shadows, gradients).
The audience is researchers/academics/tinkerers and this is a **documentation** site. This unit
applies SFDS v2 (marketing register, gold accent) across the app and rewrites the landing into
an honest documentation front door — no selling, no invented numbers. Folded into OME-666
(the ScreamingFace Client documentation ticket) per owner decision.

## Planned changes

- `public-docs/index.html` — `data-brand="marketing"`; load IBM Plex Sans + IBM Plex Mono +
  Parastoo (Google Fonts, since fonts aren't vendored locally); honest title/description/meta.
- `public-docs/src/style.css` — replace the oklch/purple/rounded/shadow token system with SFDS
  v2 tokens (values verbatim from `.claude/skills/screamingface-design/reference/tokens.css`),
  re-keyed to the app's `.dark` class; bridge Tailwind `@theme` `--color-*`/`--font-*`/`--radius`
  /`--shadow-*` onto SFDS roles; square corners, hairline borders, no shadows/gradients; remove
  the `.marketing-page` cyan palette.
- `public-docs/src/components/nb/tokens.css` — migrate raw hexes to SFDS semantic roles.
- `public-docs/src/components/layout/TheNavbar.vue` — 😱 system-emoji mark (replace off-brand
  gradient-pyramid logo), square, gold active state.
- `public-docs/src/components/layout/DocLayout.vue` — remove the banned text-gradient on the page
  title, square + hairline chrome, token-driven colors.
- `public-docs/src/pages/HomePage.vue` — rewrite into a documentation landing.

### Follow-on (same ticket, later in session)

- Editorial pass on `sf-client/Index.vue` + `sf-client/QuickstartPage.vue`: "fusion" not
  "ensemble", `url4` lowercase, flow/grammar fixes. Reverted `nb/tokens.css` to callis's original
  values so the Quickstart widgets are unchanged.
- **"Learn more" section** (renamed from "SDK"): new pages `Architecture` (first), `url4`,
  `ScreamingFace Engine`, `url4 SDK` under `/learn/*`, written from the codebase + product
  positioning and linking to `github.com/ScreamingFace/screamingface`. New `src/navigation/learn.ts`,
  new routes, navbar + landing-card updates, removed the old `/sdk` stub. Real request-architecture
  diagrams copied to `public/diagrams/` and embedded theme-aware on the Architecture page.

## Test plan

No unit-test harness in this project; this is a visual re-skin. Verification:
- Dev server renders landing + doc pages in **both light and dark** with no console errors.
- SFDS self-check passes (register/gold, square, hairline, no shadow/gradient, no raw hex where a
  role belongs, no typed all-caps, no fake metrics, 😱 as system emoji, two-family type).
- `npm run type-check` and `npm run lint` pass.
- Content audit: zero invented numbers on the landing; every landing link resolves.

## Acceptance

- Landing is a documentation front door (no product-sell, no invented metrics, no Product Hunt).
- Whole app renders in the SFDS marketing register (gold accent, Plex + Parastoo, square/hairline)
  in light and dark.
- Doc content pages (callis's) render correctly under the new theme, untouched in content.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <type-check / lint result>
- **Deviations:** <fonts via Google Fonts CDN not self-hosted; lucide icons kept over Remix — both
  noted as scoped follow-ups; anything else>

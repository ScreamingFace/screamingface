---
ticket: OME-1530
stack: scoreboard
status: in_review
started: 2026-10-08
finished:
---

# leaderboard-plausible-sections — views per leaderboard and clicks per section in Plausible

## Intent

Marketing needs to confirm the leaderboard's Plausible integration tracks views **per
leaderboard** and **per location on the page** (Asana: "Confirm that the plausible integration on
the SF leaderboard works", Q4 Get 10 SOTA, Views and Subs). Today neither works: every benchmark is
`benchmark.html?id=<id>` and Plausible strips query strings, so all boards collapse into one
`/benchmark.html` row; and no in-page click is recorded except outbound links. This tags every
pageview with the benchmark it shows and records one `Section Click` event per click on a link or
button, labelled with the page region it sits in.

## Planned changes

- `apps/scoreboard/portal/analytics.js` (new): the Plausible queue stub + `plausible.init` (moved
  out of the five pages' identical inline blocks), a `benchmark` custom property from `?id=`, and a
  delegated click listener sending `Section Click` with `section` + `label`. Pure helpers exported
  for Node, same UMD shape as `leaderboard-logic.js`.
- `apps/scoreboard/portal/{index,benchmark,about,data,spec}.html`: replace the inline init block
  with `<script src="analytics.js"></script>`; add `data-section` to the regions (rail → `nav`,
  foot → `footer`, hero/header, `catalogue`, `benchmark-tabs`, `score-bars`, `chart`, `table`, the
  four about sections).
- `apps/scoreboard/tests/portal/analytics.test.js` (new): the pure helpers.

## Test plan

- `benchmarkFromSearch`: `?id=x` → `x`; missing/empty id → none; URL-encoded id decoded.
- `labelFor`: explicit `data-track-label` wins; a `benchmark.html?id=` link labels as its id;
  then `aria-label`; then visible text, whitespace-collapsed and capped at 60 chars; empty → `(unlabelled)`.
- `sectionFor`: nearest `data-section` ancestor wins; none → `page`.
- Manual against the local preview: pageview payload carries `p.benchmark` on a board; clicking a
  card, a tab, a sort header, a copy button and a nav link each send `Section Click` with the right
  section (read from the queued calls / network payload).

## Acceptance

- Plausible breaks benchmark pageviews down by `benchmark` property.
- `Section Click` events appear with `section` and `label` properties for clicks in every region.
- Nothing about rendering changes; a blocked Plausible script causes no console error.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `data-section` on `index.html`'s `.hero-cta` (`hero` — the CTA
  sits outside the hero `<header>`) and on the `.note` blocks of `benchmark.html`/`spec.html` (`note`);
  `analytics.test.js` named at both portal-test call sites (`.github/workflows/scoreboard-tests.yml`,
  `.claude/sdlc.local.md`) so `test_portal_ci_wiring.py` passes. Rebased onto `fc8cb9ca` (rail
  breadcrumb change): kept main's rail markup and added `data-section="nav"` to it.
- **Commits:** see PR.
- **Gates:** `node --test tests/portal/*.test.js` 90/90 pass (82 existing + 8 new); `node --check
  portal/analytics.js` clean. Browser (local portal on :9106, `/v1/*` proxied read-only to prod,
  Plausible calls captured in-page since the script ignores localhost): catalogue card →
  `catalogue`/`draco-3pass`; hero CTA → `hero`; board tab → `benchmark-tabs`; sort header, spec link
  and Copy button → `table`; nav, theme toggle → `nav`; footer → `footer`; about links → their
  section. `customProperties` yields `{benchmark: <id>}` on a board and `{}` elsewhere. No console
  errors.
- **Deviations:** no spec or plan artifact — small analytics change, same precedent as
  `2026-10-06-docs-plausible-analytics` (OME-1505). Plausible site settings (register the
  `benchmark`, `section`, `label` custom properties and a `Section Click` goal) are owner actions in
  the Plausible UI, not code.

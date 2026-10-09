---
ticket: OME-1531
stack: scoreboard
status: in_review
started: 2026-10-08
finished:
---

# leaderboard-subscribe — email subscribe forms, per leaderboard and site-wide

## Intent

Let a visitor subscribe to ScreamingFace updates, or follow one leaderboard, and record in HubSpot
which board and which page placement each subscriber came from (Q4 "Views and Subs"). Spec:
`docs/spec/2026-10-08-leaderboard-subscribe.md`.

## Planned changes

- `apps/scoreboard/portal/subscribe.js` (new, UMD like `analytics.js`): pure helpers
  (`isValidEmail`, `copyFor`, `buildSubmission`) + the browser forms.
- `apps/scoreboard/portal/portal.css`: the subscribe block (extends the vendored `.signup` row).
- The five pages: the site-wide mount point above the footer and `subscribe.js`; `index.html` hero
  gets "Subscribe for updates" (black) next to "Get started" (now gold `.btn--primary`).
- Tests: `tests/portal/subscribe.test.js`, `tests/unit/test_portal_subscribe.py` (both new), the
  portal test named at both CI call sites.

## Test plan

- Node: board vs site-wide payload, consent ids per scope and with the tick-box, UTMs from the
  query string (`utm_term` ignored), visitor cookie only when present, email validation, copy.
- pytest: every page has `data-section`-tagged `data-subscribe="all"` and loads `subscribe.js`;
  `/subscribe.js` serves.
- Manual (local preview, prod data read-only): open/close the board form, invalid email, success,
  returning visitor, light/dark, 390 px; one real end-to-end submission checked in HubSpot.

## Acceptance

- A board submission lands in HubSpot with the board id, placement, page URL and UTMs, subscribed
  to Leaderboard Alerts (and ScreamingFace Updates when ticked), and creates no Clearinghouse lead.
- A site-wide submission is scoped `all` and subscribed to ScreamingFace Updates only.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Built on `leaderboard-plausible-sections` (the forms carry
  `data-section="subscribe"` for its click tracking).
- **Commits:** see PR.
- **Gates:** `run_gates.py scoreboard` green locally. End-to-end: one test submission from the
  DRACO 3-Pass page (contact `bennett+sf-subscribe-test@`) carried `draco-3pass`, `board-header`,
  `sf_subscribe_all=true`, the UTMs and page URL, was subscribed to both types with
  CONSENT_WITH_NOTICE (v4 API), and created no lead.
- **Deviations:** HubSpot setup (three contact properties, the form, two subscription types, the
  form excluded from the Clearinghouse lead workflow) was done in HubSpot, not in code. Three
  prototype layouts were reviewed in the local preview; the title-led one was chosen and the
  others removed before commit.

# about-leaderboard-page — a short About page

## Problem

The leaderboard states what it is only in fragments (the landing's three definitions, the per-board
"about" window), and the cost–quality (Pareto) explanation removed from the board page now has no
home. A research audience wants one page that says what this is, how it works, how to contribute,
and who builds it — short enough to read in a minute.

## Rule

A new `about.html` in the **marketing register** (same language as the landing): a gold mono eyebrow,
a Parastoo serif title, and hairline-separated sections, owner-approved copy:

1. **Thesis** — the best answers come from compositions (ensembles/routers/cascades); the evidence
   exists but is scattered and expensive to find. A growing community is pushing it forward; for it
   to compound it needs public recipes, stranger-rerunnable results, cost paid once, and the users
   drawing the map (four square bullets).
2. **How it works** — screamingface is an open-source toolkit; every row is a `url4` recipe; pinned
   calls + a shared cache make replaying free and building cheap. Link: Read the docs.
3. **Contribute** — anyone can submit using screamingface (linked to the docs); Apache-2.0, authorship
   kept. Links: Get started · Browse the board · Research grant.
4. **Who builds this** — built in the open, with the support of OpenMined.

The page is linked from the `about` rail link on every portal page.

## Not changed

- The grant program's own copy/logistics stay on the grants (openmined.org) page — the About page
  links to it, it does not reproduce it.
- No API change; no leaderboard logic — the page is static.

## Tests

- Static-asset: `/about.html` serves 200, includes the plausible snippet, carries the section labels
  (Thesis · How it works · Contribute · Who builds this), and the `about` rail link is present on
  index / benchmark / spec. (Additive — no existing test is modified.)

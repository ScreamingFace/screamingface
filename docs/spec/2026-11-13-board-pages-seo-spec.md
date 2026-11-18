---
title: One indexable page per leaderboard
status: proposed
created: 2026-11-13
related:
  - OME-1638 (link-preview tags and image on the portal pages)
  - OME-885 (portal source hygiene: no build step, served files carry no internal references)
  - docs/spec/2026-11-03-benchmark-catalog-summary-spec.md (the catalog summary this reuses)
---

# One indexable page per leaderboard — spec

## 1. Problem

Measured against `https://leaderboard.screamingface.ai` on 2026-11-12:

- **All boards are one document.** `benchmark.html?id=<id>` returns the same bytes for every
  id. Title `screamingface · leaderboard`, one meta description, one set of `og:`/`twitter:`
  tags, `<h1>Leaderboard</h1>`, body `Loading…`. JavaScript sets `document.title` after the API
  call; nothing sets the description or preview tags.
- **Boards cannot be discovered without JavaScript.** `/sitemap.xml` is 404. `/robots.txt`
  carries no directives. Links to boards exist only after `main.js` builds them.
- **Status codes do not describe the page.** `benchmark.html?id=does-not-exist` is 200. 38 of
  92 boards have no score and are indexable as empty pages.
- **No page declares a canonical address.** A board's URL varies with any extra or reordered
  query parameter.

Crawlers reach the site (Cloudflare shows about 2,000 crawler requests to this host in seven
days, including Googlebot, Bingbot, ChatGPT-User and PerplexityBot), so the limit is what they
are served.

## 2. Requirements

- **R1 — one stable address per board.** A path, `/benchmarks/<id>/`. The old address
  redirects to it permanently and keeps other query parameters.
- **R2 — the HTML names the board before any script runs.** Its own `<title>`, meta
  description, `<h1>` and lead text.
- **R3 — each board has its own link preview.** `og:title`, `og:description`, `og:url` and the
  matching `twitter:` tags.
- **R4 — boards are discoverable.** `/sitemap.xml` lists them; `/robots.txt` names the sitemap.
- **R5 — status and indexing are truthful.** Unknown id is 404. A board with no eligible displayed result, and a
  private board, carry `noindex`. Eligible imported results count; unreviewed or stale imports do not.
- **R6 — one canonical address.** Each board page declares `<link rel="canonical">` on the
  production origin.

## 3. Constraints

- **No build step, no new dependency** (OME-885). Pages are filled in by a route at request
  time from the existing `portal/benchmark.html`.
- **Private boards behave as today.** They stay publicly listed by `/v1/benchmarks`, their
  page loads, and no score or board field is added to their HTML.
- **Visibility stays owned by the catalog.** The route uses `list_benchmark_summaries(include_imported=True)`, which filters private boards, reads eligible imported scores in bulk and revalidates visibility after those reads, plus a separate existence check.
- **Subscribe and analytics keep working.** `subscribe.js`, `analytics.js`, `main.js`,
  `benchmark.js` and `spec.js` each read the board from `?id=` today.
- **Board fields are community-submitted.** Every value written into HTML is escaped.
- **The served static files stay byte-identical**, including bare `benchmark.html`.
- **No scores or ranks in the title or description.** Search results keep a snippet for days;
  board leads change within hours.

## 4. Out of scope

- Server-rendering the results table, and any change to the external-results merge.
- Titles or descriptions that name the leading entry or classify it as a fusion.
- Structured data, per-board preview images, slugs without the harness prefix.
- The home, about, spec and data pages (a separate unit).
- The `http` to `https` redirect and the public staging and dev hosts (edge configuration).

## 5. Open questions for the owners

- Is "verified" a standing guarantee for every listed result? If so it belongs in the title
  and description; it is left out here.
- The board route runs the whole-catalog summary query per page view, as the home page does.
  A single-board variant is the alternative if that cost matters.

## Accepted takeover scope, 2026-11-17

Implement the accepted review findings from PR 1800 while preserving current portal behavior and Kyle’s commit history. Public boards with eligible displayed imported results remain indexable.

Acceptance: GET/HEAD parity; exact redirect destinations and UTM preservation; expected database outage exceptions and unexpected programming errors; eligible/ineligible/stale/private imported boards; visibility revalidation; exact HTML metadata; real browser navigation and intercepted signup.

Tracking: OME-1953; owner authorized implementation and publication to the existing PR.

The bare `/benchmark.html` retains its static bytes with `X-Robots-Tag: noindex,follow`. Dot-segment ids are rejected rather than redirected to a different page. All page/discovery routes support GET and HEAD. Request-time store outages return uncached 503 responses; unexpected programming errors propagate.

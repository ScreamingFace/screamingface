---
title: Search metadata on the home, about, spec and data pages
status: proposed
created: 2026-11-13
related:
  - OME-1638 (link-preview tags and image on the portal pages)
  - docs/spec/2026-11-13-board-pages-seo-spec.md (per-board pages; independent of this unit)
---

# Search metadata on the home, about, spec and data pages — spec

## 1. Problem

Measured against `https://leaderboard.screamingface.ai` on 2026-11-12:

- **The home page does not say what the site is in its head.** Title
  `screamingface · benchmark receipts`; description "Public screamingface benchmark results
  with scores, providers, and local rerun links." Neither contains "leaderboard", "fusion",
  "ensemble" or "router". The page's own `<h1>` reads "The leaderboard for fusions."
- **No page declares a canonical address.** `/` and `/index.html` both answer 200, so the home
  page has two addresses.
- **`spec.html` and `data.html` are indexable with nothing on them.** Each shows content only
  with its query parameters, and the static document cannot name them.

## 2. Requirements

- **R1 — the home title and description name the site.** They use the terms in the page's own
  heading and lead: leaderboard, fusions, ensembles, routers.
- **R2 — link-preview text matches.** `og:title`/`twitter:title` equal the title;
  `og:description`/`twitter:description` equal the description.
- **R3 — home and about declare a canonical** on the production origin, equal to the `og:url`
  each already carries.
- **R4 — the spec and data pages carry `noindex,follow`.**

## 3. Constraints

- Static files only; no build step and no route.
- The home wording is brand copy. Tests assert structure and agreement between tags, not the
  sentence.

## 4. Out of scope

- Per-board pages, the sitemap and `robots.txt` (the board-pages unit).
- Server-rendering the home catalog; structured data.

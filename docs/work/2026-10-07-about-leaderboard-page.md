---
ticket: OME-1514
stack: scoreboard
status: in_progress
started: 2026-10-07
finished:
---

# about-leaderboard-page — a short About page for the leaderboard

## Intent

The leaderboard has no single page that states what it is, how it works, how to contribute, and who
builds it — the pieces are scattered (landing definitions, per-board "about" window) or missing (the
Pareto explanation was removed from the board page). Researchers want one page they can read before
trusting a number. Add a deliberately short About page (owner-approved copy) and link it from every
rail.

Stacked on `OME-1512-leaderboard-visual-refresh` (reuses its hero/section/eyebrow styles, not yet on
main); PR base is that branch until OME-1512 merges.

## Planned changes

- `apps/scoreboard/portal/about.html` — new page: hero + hairline sections (Thesis · How it works ·
  Contribute · Who builds this), reusing `.hero`/`.section-label`/`.eyebrow`/`.btn--link`.
- `apps/scoreboard/portal/index.html`, `benchmark.html`, `spec.html` — add an `about` rail link.
- `apps/scoreboard/portal/portal.css` — about-page section + bullet styles.
- `apps/scoreboard/tests/unit/test_portal_static.py` — an additive structure test for the page.

## Test plan

- Static: `/about.html` serves 200, carries the plausible snippet, has the section labels, and is
  rail-linked from every page.
- Manual: the page renders in the running portal; the rail `about` link works from all pages.

## Acceptance

- `run_gates.py scoreboard` green. About page linked from all three rails.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `portal/about.html` (new), `portal/index.html` + `benchmark.html` +
  `spec.html` (rail `about` link), `portal/portal.css` (about-page styles),
  `tests/unit/test_portal_static.py` (additive about test), `.claude/test-change-approvals/OME-1514.json`.
- **Commits:** `8270d4353` … (About page), then the copy refinements and the cite-feature removal.
- **Gates:** `run_gates.py scoreboard --base origin/main` green — append-only (the OME-1514 manifest
  pins the test_portal_static transition), ruff, format, pyright, pytest (90% cov), node portal tests.
- **Deviations:** (1) Stacked on OME-1512 (reuses its hero/section styles) — PR base is the OME-1512
  branch, retargeting to main on its merge. (2) A per-entry BibTeX "Cite" button (`buildCitation`,
  spec.js, citation.test.js) was built and then removed on owner request — the About page carries no
  citation content.

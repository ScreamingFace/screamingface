# about-leaderboard-page — plan

Spec: `docs/spec/2026-10-07-about-leaderboard-page.md`. Branch `about-leaderboard-page` off
`OME-1512-leaderboard-visual-refresh` (stacked; PR base is that branch until it merges).

1. **Page.** `portal/about.html` — hero + `.section-label` sections (Thesis · How it works ·
   Contribute · Who builds this) with the approved copy; Thesis "needs to" list as square bullets.
   Reuse the landing's `.wrap.wide.landing` width and hero styles.
2. **Rails.** Add `<a class="rail-link" href="about.html">about</a>` to index / benchmark / spec.
3. **Styles.** `portal.css` — about-page section spacing + `.about-bullets` (square bullets); airy
   prose line-height.
4. **Static test.** An additive structure test in `tests/unit/test_portal_static.py`: `/about.html`
   public, plausible snippet, section labels, rail-linked from every page.
5. **Gates** `run_gates.py scoreboard`; manual check in the running portal; ledger outcome,
   `docs/tasks` mirror + Linear filing under OME-1319 at PR-open, approval manifest, `Refs: OME-N`.

> A per-entry BibTeX "Cite" button (`buildCitation` in leaderboard-logic.js + a spec.js button +
> citation.test.js) was built and then removed on owner request; the About page carries no citation.

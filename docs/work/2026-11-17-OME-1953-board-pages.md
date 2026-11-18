---
ticket: OME-1953
stack: scoreboard
status: in_progress
started: 2026-11-17
finished:
---

# OME-1953 — Complete per-board search pages

## Intent

Implement the accepted review findings from PR 1800 while preserving current portal behavior and Kyle’s commit history. Public boards with eligible displayed imported results remain indexable.

## Planned changes

board_pages.py; scores/catalog.py; scores/baseline_store.py; board-page regression tests; test_portal_static.py; the existing spec/plan/work records; workflow test lists.

## Test plan

GET/HEAD parity; exact redirect destinations and UTM preservation; expected database outage exceptions and unexpected programming errors; eligible/ineligible/stale/private imported boards; visibility revalidation; exact HTML metadata; real browser navigation and intercepted signup.

## Acceptance

All reviewed defects addressed, required gates green, desktop/mobile previews inspected in both themes, and the existing PR updated as FilipBolt. No real subscription is sent.

## Authorization and approach

On 2026-11-17 the owner requested taking over PRs 1800 and 1801 and explicitly selected keeping both PRs and pushing the fixes as FilipBolt. The accepted review includes updating the obsolete redirect test and removing the noindex contract from the metadata tests. Kyle confirmed both indexing decisions in the PR discussion. These narrow test updates implement that authorized contract change; unrelated existing tests are preserved.

Start from current main and integrate the original PR with a merge, preserving its commit as an ancestor so the existing branch can be updated without force-pushing another author's history. Existing specs and plans are amended with the accepted review scope before implementation.

## Outcome

Implemented the accepted review scope and integrated current main without rewriting the original PR history.

- RED: regression coverage reproduced the original failures before the fixes.
- GREEN: `uv run .claude/scripts/run_gates.py scoreboard` passed: append-only guard, Ruff lint/format, Pyright, full pytest suite with the 80% coverage gate, and all configured Node portal tests.
- Combined preview with both PRs: visually inspected at 1440px and 390px in light and dark themes. No document overflow or JavaScript errors. Mixed community/imported results and an imported-only board render; the imported-only board is indexable and appears in the sitemap.
- Browser checks: legacy redirects retain tracking parameters; submission links open history; intercepted follow-board signup includes the correct board id, current page URL and UTM value. No live HubSpot submission was sent.
- Local preview: `http://127.0.0.1:9181/benchmarks/inspect-agieval_sat_en/` (local fixture data only).
- Hosted checks and review remain required before merge. This takeover does not merge the PR.


Real asyncpg connection-refusal probe: both the board route and sitemap return 503 with `Store unavailable`. Imported eligibility uses the existing row validation and one bulk joined read, followed by visibility revalidation; the existing homepage summary API contract is unchanged. The existing regex template and whole-catalogue query per request remain; caching/template refactoring is outside this fix.

## Final integration pass, 2026-11-18

Owner authorized an internal pass and merge without posting another review. The combined current-main checkout exposed a relative imported-result history link under the new nested board addresses. Route that link through the existing `ScorePortal.pageHref` helper; add a regression using the real portal scripts at an HTTPS board URL and a file URL. Preserve existing tests. Validate the full scoreboard gates and the two PRs together, and check the history navigation in a headless local preview before pushing.

Final-pass validation: the new HTTPS regression failed on the old link and passes with `pageHref`; the file-page regression also passes. Full scoreboard gates are green against the branch's main ancestor (93b103cc3). In an isolated checkout combining both PRs with current main, 110 Python tests and 46 focused Node tests pass. Headless previews at 1440px and 390px in both themes show the Updated link; following it opens the history page and loads saved versions, with zero browser errors. Local preview: http://127.0.0.1:9195/benchmarks/inspect-agieval_sat_en/. CodeQL alert 28 was dismissed as a false positive after 680 hostile redirect probes. No review was posted.

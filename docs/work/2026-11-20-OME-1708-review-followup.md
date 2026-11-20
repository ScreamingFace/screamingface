---
ticket: OME-1708
stack: scoreboard
status: in_progress
started: 2026-11-20
finished:
---

# Revision selector review follow-up

## Intent

Address Dmitry's latest review on PR #1943, authorized by Filip: accurately name historical scope when the revision list fails, preserve the no-submissions message on versioned boards with imported references, and rebase onto current main.

## Planned changes

- Keep both main's and this branch's portal suites when resolving the gate-card conflict.
- Use neutral scope wording: a scoped response identifies the displayed revision, not the current revision.
- Judge versioned-board submission status from community runs, independently of imported rows. Preserve the existing unversioned external-only presentation.
- Correct this PR's fake historical responses and expectations; add baseline-only and unavailable-list regressions. Existing tests from main remain unchanged.

## Test plan

Run corrected/new regressions before the fixes, then full scoreboard and repository gates. Visually inspect the real portal with historical/list-failure and baseline-only fixtures at desktop/mobile sizes in light/dark themes. Confirm private-board fallback and existing revision-switch protections.

## Acceptance

Historical results never claim Latest without revision-list evidence. A versioned board with no community submissions retains its message and imported rows. All applicable checks pass; the refreshed PR contains the fixes and validation evidence.

## Outcome

Implemented the neutral scope notice and versioned-board submission status in `revision-selector.js` and `benchmark.js`. Corrected this PR's historical API fixtures to return the selected revision, loaded the real external-result renderer in integration tests, and covered both response orders, unavailable lists, retained reference rows and private-board fallback.

Five regression assertions failed before the fixes; all 30 focused tests then passed, including the unchanged external-results suite. Full scoreboard gates (Python lint, format, types, coverage suite and every portal suite), repository gates and diff checks pass against main `672ac44a7`. The rebase retains both catalog-search and revision-selector suites. No tests from main were edited.

A real local scoreboard API with fixture data reproduced a historical revision-list 503 and an eligible imported-only Latest board. Headless Chromium checks at 1440px and 390px in light/dark themes show the exact neutral notice and no-submissions message, retain one result row, and report no page-wide overflow or JavaScript errors. The intentional HTTP 503 is expected. Preview: http://127.0.0.1:9201/benchmarks/review-history/?revision=bbbbbbbb and http://127.0.0.1:9201/benchmarks/inspect-agieval_sat_en/.

The two remaining review findings and the main conflict are addressed. PR #1943 remains open for review; OME-1708 is not closed by this follow-up. No API or schema changes.

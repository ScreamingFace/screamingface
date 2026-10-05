---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# All candidates as a list filter

## Intent
Apply the owner's corrected meaning: All Candidates lists every case result with ordinary pagination. Keep specific-candidate filtering and direct case lookup, without an implicit comparison mode.

## Planned changes
Order the combined list by retained case identity order, then candidate order, so matching case results sit together. Paginate 25 result rows. Keep candidate labels/previews in All, omit repeated candidate labels for one candidate. Go to selects/reveals the first matching row on the appropriate page. Update superseded comparison expectations under the explicit user instruction.

## Test plan
Combined totals, page boundaries, exact/sparse/string identity lookup, candidate switching, selected detail, retained labels, bounded reads and rapid clicks. SDK gates and live notebook.

## Acceptance
All exposes all results without showing only one case. No added comparison switch. Exact case lookup remains independent of flattened result number and does not scan prompts.

## Outcome
All now uses a 25-row list over every indexed result, with case-major ordering and an indexed first-match lookup. Selected-candidate navigation retains original order and previews. Removed the implicit comparison mode and its redundant-label suppression; no public API, result persistence, export format or source data changed.

RED: six prior comparison expectations failed against the corrected combined-list contract. GREEN: all 35 focused navigation/browser/interaction tests pass. Prior assertions were updated under the explicit user request; disk lookup and rapid-click safeguards remain covered.

Live notebook verified All Candidates range 1–25 of 46002; Go to 25 opened 276–300 of 46002 with Case 25 / candidate-0 selected; candidate-5 retained Case 25 at 26–50 of 4182; five rapid Next clicks from the combined case-25 page reached 401–425 of 46002. Restored the first All Candidates page and saved the screenshot.

Wisdom: a dropdown named All Candidates is a filter over a list. Comparing one case across candidates must be an explicit separate action if introduced later, not an implicit change of pagination semantics.

Final checks: all SDK gates green (lint, format, Pyright, full pytest ≥95% coverage, notebook checks, build and distribution). Final naming/format cleanup also passes Ruff. The append-only test check is skipped for the owner-approved change in navigation semantics; no export or persistence assertions were weakened.

---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-10
finished: 2026-11-10
---

# Finish approved external-result layout with history

## Intent

Owner identified the old comparison and Original result UI in the history preview and requested a more consistent history page. Integrate the already-approved Source button/shared comparison notes into PR 1731 and restyle the new page with the portal's existing typography/table patterns.

## Planned changes

Carry over Source button styling and one shared notes disclosure, preserving Updated links and the safety/eligibility guards. Refine history presentation using existing semantic tokens, with a concise current result summary and a responsive version table. No backend or migration changes.

## Test plan

Update only outdated presentation assertions authorized by the new UI, retain all security/ranking assertions, and add combined Source/Updated/shared-note checks. Run portal tests and full scoreboard gates. Preview mixed data on desktop/mobile in light/dark before pushing.

## Acceptance

Source matches Copy/Reproduce, repeated comparison text appears once below the board, history page matches portal styling, Updated and actual source links remain clickable. No Linear or deployment writes.

## Outcome

Integrated the previously approved Source button and shared Comparison notes into the history branch, retaining Updated links, eligibility/ranks, and safe source handling. Source now matches Copy/Reproduce: IBM Plex Sans 13px/600, 8px 16px padding, 35px height. Identical comparison text is rendered once below the mixed board; different notes retain their model names.

Restyled history as compact aligned version rows with the portal's neutral colors, borders and typography. Mobile uses two columns without page overflow. The current version is distinguished without using a winning-score color. Date labels now say Saved on and Source checked on; source-check dates appear with secondary source details. Clarified to the owner that these are save/check times, neither an evaluation date.

RED: new Source/shared-note and history-layout assertions failed before implementation. GREEN: 24 focused portal cases pass. Full scoreboard gates passed with the documented presentation-contract exception to the append-only detector; all ranking/security assertions remain. Final spacing/label polish passed the focused portal suite. No backend or migration changed.

Inspected both pages at 1440px and 390px in light/dark. Confirmed no per-row comparison controls, one shared-note group for identical wording, keyboard expansion, Updated navigation and existing external URLs. No page overflow or browser errors. Screenshots remain ignored local artifacts. Kept the earlier layout worktree untouched. No Linear/deployment writes.

---
ticket: OME-1851
stack: scoreboard
status: done
started: 2026-11-06
finished: 2026-11-09
---

# Remember the catalogue filter during a session

## Intent

Keep the visitor's Has scores choice when refreshing the homepage in the same tab.
The user's direct request authorizes this implementation.

## Planned changes

- `apps/scoreboard/portal/catalog.js`: restore and save a session preference.
- New `tests/portal/catalog-session.test.js`, wired into the scoreboard local and CI gates.
- Task mirror, spec and plan for this focused follow-up.

## Test plan

Exercise fresh sessions, both toggle directions across reloads, include-unscored,
invalid values and denied reads/writes. Existing catalogue tests remain unchanged.
Verify a local browser preview with mixed results at desktop/mobile widths and both themes.

## Acceptance

Checkbox and rendered results agree after refresh. New sessions default to checked.
Storage failures cannot prevent loading or filtering. No extra API requests.

## Outcome

- **Actual files:** catalogue controller, new session tests, both Node gate lists, and planned documents.
- **Commits:** `fix(scoreboard): remember the catalogue filter during a session` (this unit).
- **Gates:** all scoreboard gates green (ruff, format, pyright, full Python coverage suite and all named Node suites). Four new session tests and four existing catalogue tests pass; three new tests failed before the fix. Mirror status and diff whitespace checks pass.
- **Browser:** Chrome at 1440×1000 and 390×844 in light/dark. Both choices survive reload, include-unscored persists, returning from About preserves the choice, a fresh tab defaults checked, and denied storage still filters. No page errors or horizontal overflow. Screenshots inspected locally under `output/playwright/` (not committed).
- **Preview:** http://127.0.0.1:9185/ serves a captured public catalogue (90 boards, 43 scored). The preview is local and uses historical data.
- **Review:** one tab-scoped boolean, no dependency/API/schema change, and no changes to previous tests. Catch blocks deliberately isolate optional browser persistence from filtering.
- **Deviations:** ticket was filed at start under the shared checkout's earlier instructions; fetched main now specifies filing at PR-open. The existing issue is retained under OME-1282. Implementation complete; merge and deployment pending.

## Checkbox-only follow-up

Owner explicitly requested: "just the checkbox please, it's very weird to have the button".
Remove the redundant button and handler, redirect empty-state guidance to the checkbox,
and replace button-path tests with checkbox-path tests preserving search and refresh coverage.
The existing JS test edits are authorized by that contract change. OME-1709 documents
that the gate cannot yet recognize exact JS approvals; record a byte-exact manifest
and run the full stack checks with the documented one-time append-only exception.
No gate implementation or CI checks are weakened. All stack checks passed with
`--skip-append-only` for this authorized contract change; the normal gate confirms
the known unsupported-JS limitation. Eight catalogue tests pass. Chrome verifies
checkbox-only search recovery, persistence and denied storage, with desktop/mobile
light/dark screenshots inspected and no overflow or page errors. The button is absent
from the DOM. Preview remains http://127.0.0.1:9185/.

## Native search-clear follow-up

Owner requests removing Clear search because the field already has an ×. Remove
the duplicate control and event handler, retain the existing input-based filtering,
and update the authorized clear-path test. Verify native × clearing, paging reset,
focus and unchanged scored preference in desktop/mobile light/dark previews.

Native-clear validation: all scoreboard stack checks pass with the same documented
JS contract-change exception. Eight catalogue tests pass. Chrome's actual native ×
was clicked at desktop/mobile widths in both themes: query becomes empty, first nine
cards return, focus stays in the field, and the scored preference stays unchanged.
All four populated-search screenshots were inspected. No page errors or overflow.

## Closure — 2026-11-09

Merged [PR #1702](https://github.com/ScreamingFace/screamingface/pull/1702) on 2026-11-09 as `28a98758e4d5f42aee2c12c37056c26d82f0fcbc`. Linear is Done.

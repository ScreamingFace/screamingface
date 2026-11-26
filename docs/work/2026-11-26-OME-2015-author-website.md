---
ticket: OME-2015
stack: scoreboard
status: in_progress
started: 2026-11-26
finished:
---

# OME-2015-author-website — let authors link a personal website on the leaderboard

## Intent

Let a credited author attach a personal `website` to their `authors_metadata` entry
(keyed by email, per-submission, no new account model) and have their name render as
an `<a href>` on the leaderboard, the spec history table, and the score detail page,
falling back to plain text when absent. Rides the existing `authors_metadata` JSON
column; `website` validates with the same http/https-only, no-userinfo, length-cap
rules as `paper_url`.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/credit_metadata.py` — add `WEBSITE_KEY` and
  route it through `_url_problem` (the same validator `paper_url`/`url` use).
- `apps/scoreboard/src/scoreboard/scores/schemas.py` — add `authors_metadata` (+ its
  key-masking `field_serializer`) to `LeaderboardEntry` and `SpecHistoryRow`
  (`ScoreSchema` already carries it).
- `apps/scoreboard/src/scoreboard/routes/leaderboard.py` — mirror the same field +
  serializer onto `RankedLeaderboardEntry` and `HistorySubmission`; wire
  `_history_submission`.
- `apps/scoreboard/src/scoreboard/scores/store.py` — add `authors_metadata` to
  `_RAW_ROW_FIELDS`/`_NULLABLE_RAW_FIELDS`, `_build_leaderboard_query`'s two SELECTs,
  `_OWNED_COLUMNS`, `_HISTORY_COLUMNS`.
- `apps/scoreboard/portal/main.js` — `formatAuthors(values, metadata)` returns a
  DocumentFragment: an `<a href>` (website, `full_name` as label) per author with one,
  plain text otherwise.
- `apps/scoreboard/portal/benchmark.js` (row renderer) and `portal/spec.js`
  (`historyRow`) — pass `entry.authors_metadata` / `s.authors_metadata` through to
  `formatAuthors` and append its fragment into the authors `<td>`.
- New portal test file for `formatAuthors` (named explicitly in `sdlc.local.md` +
  `.github/workflows/scoreboard-tests.yml` per OME-798), plus new cases appended to
  `apps/scoreboard/tests/unit/scores/test_credit_metadata.py`.

## Test plan

- `website` passes/refuses exactly like `paper_url` (scheme, user-info, length,
  non-string) — appended parametrize cases.
- `authors_metadata` flows from submit → `leaderboard()` / `list_owned_entries` /
  `list_for_spec` → JSON, key-masked the same way `ScoreSchema` already masks it;
  `website`/`full_name` pass through the mask unchanged (confirms the privacy note:
  masking is scoped to the author KEY, not the entry's fields).
- `formatAuthors([...], {...})` renders an anchor when `website` is a safe http(s)
  URL, plain text otherwise, and an em dash for no authors.

## Acceptance

- A submitter can set `authors_metadata["an@email"] = {"website": "...", "full_name": "..."}`
  and see that author's name link to the site on the leaderboard, the spec history
  table, and the score detail page.

## STOP — append-only test conflict (2026-11-26), resolved via owner-approved contract change

Implementing the portal half as specified required editing three already-committed
tests in `test_multiple_authors.py` (two literal call-site substring checks, one
every-field-non-default fixture guard). Parked in Triage with the question/options/
recommendation posted to the Linear issue; option A (edit all three) confirmed
directly by Filip, to be recorded via `.claude/test-change-approvals/OME-2015.json`
per the OME-1468 byte-exact-approval mechanism (precedent: OME-1852).

A fourth, previously-undiscovered conflict of the same shape turned up during the
full-suite sweep after implementing: `test_history_rows_carry_only_the_history_columns`
in `test_credit_metadata_review_round2.py` (an exhaustive `model_fields` guard on
`SpecHistoryRow`). Its fix (append `"authors_metadata"` to the asserted set) is
prepared and included in the same approval request, pending confirmation it's in scope
alongside the original three.

A fifth hazard was found and fixed WITHOUT needing approval: `formatAuthors` initially
returned a bare `DocumentFragment`, which broke four existing portal JS test fixtures
(`graded-note.test.js`, `paper-link.test.js`, `reproduce-button.test.js`,
`spec-meta-lines.test.js`) that render a full row but never defined
`document.createDocumentFragment`. Redesigned to return an inline `<span>` wrapper
(built with the file's own `el()`) instead — zero other test files needed touching,
and all four now pass unmodified.

All four approval-gated edits are implemented and verified green in the working tree,
but held UNCOMMITTED pending `.claude/test-change-approvals/OME-2015.json`, created by
Filip himself, before the commit that includes them.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `apps/scoreboard/src/scoreboard/scores/credit_metadata.py` — `WEBSITE_KEY`, routed through `_url_problem`.
  - `apps/scoreboard/src/scoreboard/scores/schemas.py` — `authors_metadata` + masking serializer on `LeaderboardEntry`, `SpecHistoryRow`.
  - `apps/scoreboard/src/scoreboard/routes/leaderboard.py` — same on `RankedLeaderboardEntry`, `HistorySubmission`; `_history_submission` wired.
  - `apps/scoreboard/src/scoreboard/scores/store.py` — `authors_metadata` added to `_RAW_ROW_FIELDS`/`_NULLABLE_RAW_FIELDS`, both `_build_leaderboard_query` SELECTs, `_OWNED_COLUMNS`, `_HISTORY_COLUMNS`.
  - `apps/scoreboard/portal/main.js` — `formatAuthors(values, metadata)` returns an inline `<span>` wrapper; anchor per author with a safe http(s) website, plain text otherwise.
  - `apps/scoreboard/portal/benchmark.js`, `apps/scoreboard/portal/spec.js` — callers updated to pass `authors_metadata` through.
  - `apps/scoreboard/tests/portal/format-authors.test.js` — new, registered in `.claude/sdlc.local.md` + `.github/workflows/scoreboard-tests.yml`.
  - `apps/scoreboard/tests/unit/scores/test_credit_metadata.py` — new `website` validation + masking cases (pure additions).
  - `apps/scoreboard/tests/unit/test_multiple_authors.py` — 3 owner-approved edits + 1 new end-to-end test (pure addition).
  - `apps/scoreboard/tests/unit/test_credit_metadata_review_round2.py` — 1 proposed edit (pending confirmation alongside the three).
- **Commits:** none yet — held pending `.claude/test-change-approvals/OME-2015.json`.
- **Gates:** `pytest --cov=scoreboard --cov-fail-under=80`: 2385 passed, 145 skipped, 92.80% coverage. `ruff check` / `ruff format --check`: clean. `pyright`: 0 errors. Full portal `node --test` gate line (incl. `format-authors.test.js`): 276 passed. All other portal test files individually green.
- **Deviations:** none from the approved plan beyond the 4th test-edit discovery and the fragment→span redesign, both recorded above.

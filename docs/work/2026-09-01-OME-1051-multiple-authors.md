---
ticket: OME-1051
stack: scoreboard
status: done
started: 2026-09-01
finished: 2026-09-02
---

# OME-1051 — Support multiple authors for leaderboard submissions

## Intent

A Fusion is often built by more than one person, and today the board can only name the account
that pressed submit. `submitted_by` is doing two jobs at once: it is the authorization subject
(who may read this row on a private board, who owns the idempotency key) and it is the only person
the portal can currently show. This unit separates the concepts visibly: the existing column
becomes **Submitter**, a new **Authors** column carries credit, and `submitted_by` remains the
authorization subject. A team can name every contributor without weakening ownership or exposing
addresses.

Epic. The per-landing sub-issues are `OME-1052` (display, scoreboard), `OME-1053` (client sends
the list, py-screamingface) and `OME-1054` (a resubmission updates the stored list).

## Planned changes

- Add nullable author-list storage with backwards-compatible read fallback to `submitted_by`.
- Validate one to ten syntactically valid email addresses on submission.
- Publish local parts only while preserving full addresses in Python-mode/staff data.
- Display submitter and credited authors as separate leaderboard and history columns without
  changing private-board ownership.
- Let a duplicate resubmission correct mutable submission metadata, including an explicit author
  list, without changing recipe identity.

## Test plan

- Schema boundary tests for the author count, address shape and per-address length.
- Store/API tests for legacy fallback, explicit lists, privacy ownership and dedup corrections.
- JSON serialization tests proving every author is trimmed to its local part while Python mode
  retains full addresses for staff exports.
- Portal tests for rendering all authors on leaderboard and history rows.

## Acceptance

- Existing submissions display their submitter as the sole author without a backfill.
- Explicit author lists contain 1–10 valid email-shaped strings and are displayed in order.
- Authors never gain private-board access; ownership remains scoped to `submitted_by`.
- Public JSON never exposes author domains; staff/Python-mode data retains full addresses.
- Resubmitting an identical candidate with an explicit corrected author list updates that row.

## Outcome

- **Actual files:** as planned, plus two the plan did not anticipate — a review pass found a
  defect and a misleading status code:
  - `scores/store.py` — `list_owned_entries` was not carrying `authors`. It hand-builds
    `LeaderboardEntry`, so the omission took the DTO default and **degraded silently instead of
    raising**. It landed on the one surface where it does the most damage: a private board is
    currently the only place a participant sees a credit line at all (OME-894 D2 scopes reads to
    the submitter, and `entries` is empty for everyone). Proven by execution before the fix —
    a submission carrying `[alice, bob]` read back as `None` there while history read it
    correctly.
  - `scores/store.py` + `routes/scores.py` — a lost update race raised `IntegrityError`, which
    subclasses `OperationalError` and so answered **503 store-unavailable**. A race is not the
    store being down. Now `ConcurrentScoreUpdate` → **409**, for the same reason
    `BenchmarkVisibilityChanged` is a 409: nothing is wrong with the request and a retry resolves
    it.
- **Commits:** see `Refs: OME-1051` on this branch.
- **Gates:** ALL GREEN — ruff check, ruff format, pyright, pytest (556 passed / 3 skipped, 88%
  coverage), node portal tests. Run with `--skip-append-only` per the decision below.

## Deviations

**Prior tests modified — owner-approved, 2026-09-02 (sdlc rule 5).** Six sites, approved
explicitly rather than waved through, and each carries an inline comment naming the approval so
the next reader is not left guessing:

| Site | Why it could not be avoided |
| -- | -- |
| `test_leaderboard_routes.py` history key set | asserted with **exact** set equality; the public payload gained a field |
| `_PUBLIC_BOARD_ENTRY_FIELDS` | same |
| `_PUBLIC_HISTORY_ITEM_FIELDS` | same |
| `test_ome894_guard_public_board_is_unchanged_anonymously` | added an assertion that author domains are redacted — the guard pins what an anonymous caller sees, and `authors` is now part of that |
| `test_ome894_guard_public_history_is_unchanged_anonymously` | same |
| `test_owned_entries_project_every_declared_field_from_the_row` | `authors` is DERIVED, not copied, so a verbatim row comparison is the wrong expectation for it alone |

The exact assertions were **kept exact rather than loosened to subset checks**, following the
OME-775 precedent recorded three lines above one of the edits. A subset check would let a future
field enter the public payload with no test noticing.

**A guard written to catch this exact bug did not catch it.**
`test_owned_entries_project_every_declared_field_from_the_row` compares each DTO field to the row,
and its fixture leaves the nullable ones unset — so `None == None` passed for a field the
projection never copied. A guard of that shape is only as strong as its fixture.
`test_owned_entries_carry_every_field_with_a_non_default_value` now asserts that every nullable
field in the fixture differs from its DTO default, so the comparison cannot be vacuous again.
Mutation-checked: reverting the `list_owned_entries` fix fails the new guard while the old one
still passes.

**Two compatibility wrinkles, accepted rather than fixed here:**

- Both columns show the same value for every legacy row and every client that does not yet send
  `authors=` — i.e. all of them until `OME-1053` ships. That is the cost of decision 4.
- A row written under `auth_mode: disabled` stored whatever the body claimed as `submitted_by`.
  `OME-1054`'s correction requires an exact match against the now-verified address, and a mismatch
  **skips the update silently**, so a participant may be unable to add co-authors to a historic
  submission. Staff can correct such a row directly.

**Verified, not assumed:** a pre-migration row (`authors` NULL) reads as `[submitted_by]` on all
three read paths and its `content_hash` is unchanged, so there is no display regression and no
dedup churn. Had `authors` entered recipe identity, every existing recipe would have created a
duplicate row on its next submission.

**Closes `OME-1054` as well as `OME-1051`.** Spec §7 requires they ship together: dedup discards a
corrected author list, so shipping D1 ("the submitter is responsible for their own omission")
without the correction path would make it a trap rather than a rule.

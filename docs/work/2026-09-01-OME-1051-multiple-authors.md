---
ticket: OME-1051
stack: scoreboard
status: in_progress
started: 2026-09-01
finished:
---

# OME-1051 — Support multiple authors for leaderboard submissions

## Intent

A Fusion is often built by more than one person, and today the board can only name the account
that pressed submit. `submitted_by` is doing two jobs at once: it is the authorization subject
(who may read this row on a private board, who owns the idempotency key) and it is the credit
line the portal prints under a column already labelled **"Author"**. This unit separates them —
`authors` becomes the credit, `submitted_by` stays the authorization subject — so a team can put
every contributor's name on a result without either weakening ownership or exposing addresses.

Epic. The per-landing sub-issues are `OME-1052` (display, scoreboard), `OME-1053` (client sends
the list, py-screamingface) and `OME-1054` (a resubmission updates the stored list).

## Planned changes

Spec only in this pass — `docs/spec/2026-09-01-OME-1051-multiple-authors.md`. Implementation is
gated on owner approval and lands under the sub-issues.

## Test plan

Deferred to the sub-issues. The invariant that must carry a test wherever the field is published:
an author address is trimmed to its local part on every JSON read path, exactly as `submitted_by`
is (OME-834). A test that asserts the trim on `submitted_by` but not on `authors` would pass while
the feature reopens the harvesting hole OME-834 closed.

## Acceptance

- Spec records the two owner decisions of 2026-08-31 and the reasoning behind the storage,
  publishing, dedup and privacy choices.
- Every question the spec cannot answer from code is listed for the owner rather than assumed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

---
ticket: OME-1109
stack: scoreboard
status: done
started: 2026-09-08
finished: 2026-09-08
---

# OME-1109 — Published author credits

## Intent

Publish a truthful multiple-author credit line: collapse repeated identities and disambiguate
distinct people whose email addresses share a local part, without changing stored audit data or
the privacy form of any non-colliding address.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/schemas.py` — shared author identity, validation, and
  public serialization behavior.
- `apps/scoreboard/tests/unit/test_multiple_authors.py` — additive validation, publication,
  persistence, export, order, and privacy regressions.
- `docs/tasks/2026-09-08-OME-1109-author-credits.md` — task mirror.
- `docs/spec/2026-09-08-OME-1109-author-credits.md` — approved behavior contract.
- `docs/plan/2026-09-08-OME-1109-author-credits.md` — implementation sequence.
- This ledger.

## Test plan

- RED: exact and case-variant repeated addresses publish once in first-seen order.
- RED: distinct authors sharing a local part publish distinguishable domain-bearing values.
- Boundary: non-colliding authors remain local-part-only; collision comparison ignores case.
- Boundary: eleven entries representing ten identities validate unchanged; eleven distinct
  identities fail.
- Boundary: an oversized repeated-identity list fails the independent 4 KiB field envelope.
- Persistence/privacy: the database and staff JSONL retain the exact submitted list while public
  JSON applies the publication transform.
- Regression: all existing multiple-author tests and the full scoreboard gate remain green.

## Acceptance

- Public credit lists contain one entry per case-insensitive complete address.
- Domains are visible only for distinct identities colliding on a local part within that row.
- Storage and staff export are byte-for-entry identical to the submitted author list.
- The ten-author limit counts distinct people and all official scoreboard gates pass.
- Repeated author entries cannot make the public write field unbounded.

## Outcome

- **Actual files:** the planned shared author validation/publication seam in
  `scores/schemas.py`; three additive tests in `test_multiple_authors.py`; and the planned
  task/spec/plan/ledger artifacts. No model, migration, store, portal, Client, or #841 file was
  changed.
- **Commits:** one conventional Scoreboard feature commit on `OME-1109-author-credits`; the
  immutable commit and eventual squash sha are recorded in the PR/Linear close record.
- **Gates:** focused multiple-author suite 24 passed; full Scoreboard pytest 620 passed / 3
  skipped / 3 deselected; `run_gates.py scoreboard --base origin/main` ALL GREEN — append-only,
  Ruff check, Ruff format, Pyright, full pytest coverage ≥80%, and all three portal test files.
- **Deviations:** the wisdom pass added a separate 4 KiB serialized author-list cap. Without it,
  changing the ten-entry limit to ten distinct people would make repeated entries an unbounded
  public write. The Client's `_submission_authors` still limits raw entries to ten, so it rejects
  the accepted 11-entry/10-person boundary before HTTP; that belongs to a separate
  `py-screamingface` work item under the repository's cross-landing rule and was not hidden inside
  this Scoreboard change.

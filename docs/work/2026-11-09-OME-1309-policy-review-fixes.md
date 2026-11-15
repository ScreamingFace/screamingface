---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-09
finished: 2026-11-09
---

# Review corrections

## Intent

Reject database-incompatible text in baseline metadata before persistence on both supported databases.

## Planned changes

Reuse validate_storable_json after existing metadata size/depth checks. Exercise NUL and lone surrogates in comparison notes and arbitrary nested keys/values, valid Unicode, batch no-write behavior and legacy read exclusion. Carry the parent metadata fixes into this stacked PR.

## Test plan

New regression tests first; run on isolated SQLite and PostgreSQL databases. All prior tests remain unchanged. Run scoreboard gates and inspect the final diff.

## Acceptance

All reported defects covered, previous contracts preserved, no schema or dependency changes, correct GitHub identity on each write.

## Outcome

Added the existing validate_storable_json check to bounded metadata validation after depth/size checks. Both import and read schemas reject NUL and lone surrogates in nested keys/values. Normal Unicode and multiline text remain unchanged. Added 14 regression cases and named both the new module and existing policy suite in PostgreSQL CI.

Reproduced 13 failing cases on SQLite and PostgreSQL before the fix (one valid-text control passed). All 62 policy/storage tests passed on both databases afterward. Rebased the dependent policy commit onto metadata correction 1f05ea235, resolving only the overlap in baseline_store.py to preserve both locked timestamp stamping and policy validation. Combined PostgreSQL tests: 120 passed. Full scoreboard gates green: append-only against the previously reviewed head, lint, format, typecheck, full Python coverage suite and all registered portal tests. Existing tests unchanged.

Wisdom review: reuses the database-safe validator rather than duplicating Unicode rules. Does not change the comparison policy, schema, dependencies or user interface. No rejected metadata reaches persistence. Read-side validation protects old malformed rows too.

Commit: fix(scoreboard): reject unstorable external comparison metadata (this commit).
Deviations: continued an existing PR in an isolated worktree and restacked it on its required parent; no Linear writes. PostgreSQL 15 locally; hosted CI uses its configured PostgreSQL service.

# Implementation plan

1. Add behavior tests for snapshot retention, no-op refreshes, provenance-only changes, legacy edits, rollback and overlapping writes.
2. Add a revision model and migration. Capture legacy state before overwriting; save each changed current snapshot under the upsert's row lock.
3. Add explicitly serialized public history and bounded pagination; test attribution exclusion and board scoping.
4. Add Updated link and standalone history page; test current/previous labels, safe source links, empty/error states and pagination.
5. Run migrations and concurrency regressions on disposable PostgreSQL, then full scoreboard/repo gates. Preview mixed data in both themes at desktop/mobile sizes before preparing a PR.


## Review correction, 2026-11-12

Public reads must not lock the current row: read its revision, then restrict immutable snapshots to that revision or earlier. Imports continue to lock and commit snapshots atomically. Compare JSON numbers by decimal value while preserving boolean/string distinctions. Historical comparison notes use the same fallback as board notes. Verify PostgreSQL concurrency and local desktop/mobile previews before updating #1731.

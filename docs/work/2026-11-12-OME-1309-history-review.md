---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-12
finished: 2026-11-12
---

# External history review corrections

## Intent

Address the verified findings on PR #1731, authorized by the owner: "and can we improve on #1731" (2026-11-12). Preserve the approved Source/shared-notes presentation and public history contract. Do not merge #1731 in this iteration.

## Planned changes

Remove read-side row locks while bounding immutable versions by the observed current revision. Normalize JSON numeric comparison without conflating booleans and numbers. Share comparison-note fallback between board and history. Correct the prior ledger/PR claims and provide exact-file test approval records. Document an operator-only takedown procedure; update the E20 mirror without closing the epic.

The test approval checker currently supports TypeScript but not JavaScript; extend its existing exact-blob approval path to JavaScript tests with positive and fail-closed regressions. No broad skip or gate bypass.

## Test plan

Reproduce reader blocking and exponent-number duplicate history on disposable PostgreSQL. Add snapshot-boundary and nested numeric/type regressions. Test comparison-note fallback with the actual portal helper. Run the full scoreboard and repository gates against origin/main without skip-append-only, plus PostgreSQL regressions. Inspect a local mixed-data history preview at desktop/mobile sizes in both themes before updating the PR.

## Acceptance

Readers remain responsive during an uncommitted import; version labels and paging stay consistent; identical JSONB values do not create revisions; historical notes match the board; approval records describe the actual changed assertions. Original submissions and live databases are untouched.

## Outcome

Implemented all planned corrections. Before the fix, the new PostgreSQL blocking/numeric cases failed (5 failures); after the fix, all 32 history, migration and visibility cases passed on disposable PostgreSQL 15. The 25 focused portal tests and 49 approval-checker tests passed.

Full scoreboard and repository gates passed against origin/main without an append-only bypass. The exact-file approval now covers the two existing contract-test changes, and its JavaScript handling rejects unapproved bytes and other branches. No existing test assertions were edited during this review correction.

Inspected the local history preview at 1440px and 390px in both light and dark themes. All four renders show three versions, preserve the legacy comparison note and source links, and have no horizontal overflow. Fixtures are illustrative and screenshots remain outside the repository.

Merged current main, including #1730, into the branch and retained both the accessibility rules and the shared comparison/history styles. PR #1731 remains open for re-review; no live import or deployment was performed.

---
ticket: OME-1307   # epic; the spec unit files no leaf of its own
stack: repo
status: in_progress
started: 2026-10-06
finished:
---

# e14-reproducible-submission-spec — the minimal E14 spec (rebuild)

## Intent

E14 (OME-1307) makes each leaderboard submission a reproducible research artifact. The first build
(24 PRs, #1158–#1181) was closed and deleted on 2026-10-06 so that the owner can rebuild it from
scratch. This unit writes the new, minimal spec. The spec reuses the gateway's global cache (it is
content-addressed, write-once and never expires) as the cache version. It does not copy rows, sign
receipts or issue replay grants.

## Planned changes

- `docs/spec/2026-10-06-e14-reproducible-submission/00-overview.md`
- `docs/spec/2026-10-06-e14-reproducible-submission/erd.md`
- `docs/spec/2026-10-06-e14-reproducible-submission/prd/*.md` (4 PRDs)
- `docs/spec/2026-10-06-e14-reproducible-submission/contracts.md`
- `docs/spec/2026-10-06-e14-reproducible-submission/test-plan.md`

## Test plan

- Docs only. Each code anchor is checked against `origin/main` at `4d81004e1`.

## Acceptance

- The owner approves the spec in plain words before any plan or code.
- The Linear leaves OME-1433..1437 match the PR plan in `00-overview.md` §6.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:** docs only
- **Deviations:**

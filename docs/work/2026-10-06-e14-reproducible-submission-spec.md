---
ticket: OME-1307   # epic; the spec unit files no leaf of its own
stack: repo
status: done
started: 2026-10-06
finished: 2026-10-08
---

# e14-reproducible-submission-spec — the minimal E14 spec (rebuild)

## Intent

E14 (OME-1307) makes each leaderboard submission a reproducible research artifact. The first build
(24 PRs, #1158–#1181) was closed and deleted on 2026-10-06 so that the owner can rebuild it from
scratch. This unit writes the new, minimal spec. The spec reuses the gateway's global cache (it is
content-addressed, write-once and never expires) as the cache version. It does not copy rows, sign
receipts or issue replay grants.

On 2026-10-08 the owner and peers replaced the cache version with a **frozen copy** (Q11–Q21).
`02-frozen-copy-design.md` is binding; where an older file disagrees, it wins.

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
  - Spec: `00-overview.md`, `02-frozen-copy-design.md` (binding, approved 2026-10-08), `erd.md`,
    `contracts.md`, `test-plan.md`, `prd/metadata-ownership.md`, `prd/cache-version-capture.md`,
    `prd/reproduce.md` (the last two are superseded in part by `02-frozen-copy-design.md`).
  - Plans in `docs/plan/2026-10-06-e14-reproducible-submission/`: `00-common.md`, `A1`, `A2`, `B2`,
    `B4`, `B5`, `C1`, and the frozen-copy plans `F-B1`, `F-B3`, `F-B4`, `F-B5`, `F-C1`.
  - This ledger.
- **Commits:** see `git log --oneline origin/main..e14-reproducible-submission-spec` (14 commits).
- **Gates:** docs only. Stack `repo` passes at the top of the stack (`e14-c1-docs`).
- **Deviations:**
  - The owner approved the spec on 2026-10-06, then replaced the cache version with the frozen copy
    on 2026-10-08. The cache-revision mechanism (label, registry, `only-if-cached`, revisions
    endpoint) is removed from the stack. The "cut 01" plan of 2026-10-07 was dropped with it.
  - Leaves: OME-1437 (url4 fingerprint) is cancelled. OME-1433..1436 were rewritten for the frozen
    copy. B2 is OME-1045. C1 files its leaf at PR-open.
  - The PR plan grew from the §6 table to one linear stack: spec → B1 → B2 → B3 → A1 → B4 → A2 →
    B5 → C1.

## Rebase onto main (2026-10-08)

- The whole stack was rebased onto `origin/main` `4cd063445` (87 new commits on main) with
  `git rebase --update-refs`. Backups of the old tips: `refs/e14-backup/pre-rebase-2026-10-08/*`.
- 8 conflicts, each recorded in the ledger of its PR: B2 and B3 (`world/connector.py`), B3 (failure
  code sets), A1 and B4 (portal test lists), B5 (`report.py`, public-surface snapshot).
- One new commit on B3: the normal-run test checks only the E14 header names.
- Gates pass for every PR against the branch below it (`--skip-append-only`). The approved test
  edits are unchanged: gateway 1 file, engine 11, SDK 2.
- Not run on this machine: the Postgres, NATS and e2e lanes.
- Flaky only under parallel load: aigateway `test_unknown_user_timing_close_to_wrong_password`, SDK
  `test_client_run` interrupt tests. Each passes alone.

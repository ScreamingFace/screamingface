---
ticket: OME-1776
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-29
finished:
---

# release-notes-commit-depth — release notes cover every commit since each package's last release (OME-1138 close-out L2)

## Intent

release-please collects at most `commit-search-depth` commits per run, 500 by default
(`DEFAULT_COMMIT_SEARCH_DEPTH` in release-please `src/manifest.ts`, passed as the merge-commit
iterator's `maxResults`). On 2026-10-29 the 500th commit back from `main` is `39608ba4e`
(2026-10-13), while every package's last release is far older (2926 commits since the `v0.2.0`
tag). The open release PRs #512 (aigateway 1.0.0), #1386 (screamingface-engine 1.6.0) and #1385
(url4 1.6.0) therefore list none of `e8c7d2622` (#1061), `3083640b6` (#1114), `df6e9b92d` (#1082,
a breaking change) and `641601f37` (#1231). The Engine release would ship a breaking change as a
minor. Raising the depth to 5000, kept permanently (owner, 2026-10-29), lets the next run see the
whole history since each last release. The aigateway 0.2.1 draft release is left as it is.

## Planned changes

- `release-please-config.json`: top-level `"commit-search-depth": 5000`.
- This ledger.

## Test plan

- Configuration only, no RED (close-out plan L2). Checks: the config parses as JSON and the key is
  a top-level number; the `repo` gate passes.
- After merge, the next release-please run regenerates #512, #1386 and #1385. They list #1061 and
  #1114 (aigateway), #1082 and #1231 (screamingface-engine, proposing 2.0.0), #1231 (url4).

## Acceptance

- `uv run .claude/scripts/run_gates.py repo` passes.
- After merge, the three release PRs carry the entries above.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `release-please-config.json` (one line), this ledger, the mirror, and the
  close-out spec and plan (`docs/spec/2026-10-29-ome-1138-closeout.md`,
  `docs/plan/2026-10-29-ome-1138-closeout.md`), which land with the first close-out leaf.
- **Commits:** pending: `ci(release): search the full history since each last release`.
- **Gates:** `run_gates.py repo --base origin/main`: ALL GATES GREEN (append-only,
  test_run_gates, test_check_mirror_status, test_pre_push, check_loop_parity,
  check_mirror_status). `verify_chart_wiring.py`: 121/121 checks passed. The config parses and
  `commit-search-depth` is the top-level integer 5000.
- **Deviations:** none. Still open after merge: confirm the regenerated #512, #1386 and #1385,
  then edit the aigateway 1.0.0 notes so the removed purge command is not listed under Features.

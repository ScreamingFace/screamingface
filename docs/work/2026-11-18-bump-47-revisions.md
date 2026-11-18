---
ticket: OME-1958
stack: screamingface-engine
status: done
started: 2026-11-18
finished: 2026-11-18
---

# bump-47-revisions — move the 47 revisions OME-1907's grading change touches

## Intent

OME-1907 (#1783, merged) changed how 47 Benchmarks read a wrapped answer letter such as
`ANSWER: $B`, and held their published revisions. Under the owner's 2026-11-17 rule a grading
change moves the revision, and the OME-1909 re-grade (#1896) moves the old entries onto the new
id from their pinned caches. The bump was built in #1896 and moved here on 2026-11-18 (owner),
so the re-grade ships first without moving any leaderboard, and this PR merges and deploys right
before the batch re-grade: old entries are off the Latest board for minutes.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`: 47 rows get the new
  `published_revision` (their fingerprint) and `regradable_from` (old id, Case Digest).
- `tests/unit/inspect/test_published_revisions.py`: 47 literals, each comment naming its old id.
- `tests/unit/inspect/test_benchmark_fingerprints.py`: the OME-1907 comment says the ids moved.
- Engine `CHANGELOG.md`: one line listing the 47 and why.

## Test plan

- `test_published_revisions.py` pins every new id; `test_benchmark_fingerprints.py` shows each
  equals its fingerprint; assembly (`_check_regradable_from`) refuses a stale Case Digest.

## Acceptance

- All 47 rows publish their fingerprint and list their old id with today's Case Digest.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1958.json`, this ledger and the mirror.
- **Commits:** the bump (cherry-picked from 2347b5810 with its references moved from OME-1909 to OME-1958), and this docs commit. Stacked on #1896 (`OME-1909-regrade-from-pinned-cache`), because `regradable_from` lands there.
- **Gates:** Engine with the inspect extra: 246 passed in `test_published_revisions.py`, `test_published_revision.py`, `test_benchmark_fingerprints.py`, `test_regradable_from.py`, `test_benchmark_bump_regradable.py`, `test_benchmark_foundation.py`.
- **Deviations:** the manifest pins every prior-test edit on this branch against main, #1896's ten included, because the checker accepts only a manifest naming the current branch; re-pin to this PR's two files once #1896 merges.
- **Owner verify:** merge only after #1896 is deployed, and right before the batch: post to the team (47 boards move), merge, wait for the Engine and the Scoreboard pins to reach prod, check https://leaderboard.screamingface.ai/v1/leaderboard/inspect-mmlu_pro shows `4efebd6cc74c2dca`, then run the batch re-grade in OME-1958's steps.

---
ticket: OME-1791
stack: screamingface
status: in_progress
started: 2026-10-30
finished:
---

# runner-config-override - honor a custom runner world in the local runtime

## Intent

Bring external contribution PR #1553 onto current `main` after review confirmed its runner-world
override and preflight behavior. A selected config must be validated by the canonical Engine loader
before `restart` stops a healthy stack. The documented Gateway inventory must use the full decoded
model ID and both environment variables must be repeated on later starts.

## Planned changes

- Merge current `main` into the contributor branch without rebasing or force-pushing.
- Record the owner-approved one-line transition in
  `tests/test_runtime_benchmark_assets_dir.py` with a byte-exact manifest.
- Add this ledger and the OME-1791 task mirror.
- Add `Refs: OME-1791` to PR #1553.

No product source is changed beyond the contribution already under review.

## Test plan

- Focused runtime CLI and benchmark-assets tests.
- Full `screamingface` gate on the merged head, including append-only, lint, format, typecheck,
  pytest coverage, notebook, build, and distribution checks.
- Current GitHub CI on the pushed exact head.

## Acceptance

- The full local gate passes with the exact test transition approved.
- The PR branch contains current `main` through one merge commit and remains conflict-free.
- Current-head CI is green before approval.

## Outcome

- **Actual files:** `.claude/test-change-approvals/OME-1791.json`,
  `docs/tasks/2026-10-30-OME-1791-runner-config-override.md` and this ledger. Product source and
  tests remain the external contribution's exact diff.
- **Commits:** `7e2262627` merges current `main` into the contributor branch; the process-record
  follow-up is the commit carrying this ledger, mirror and manifest.
- **Gates:** focused runtime suites `97 passed`; `run_gates.py screamingface --base origin/main`
  ALL GATES GREEN (approved append-only transition, Ruff, format, Pyright, full pytest coverage,
  notebook check, build and distribution); `run_gates.py repo --base origin/main` ALL GATES GREEN.
- **Deviations:** GitHub's update-branch mutation was blocked because the OAuth token lacks workflow
  scope; the equivalent non-force merge was prepared locally for SSH push. The first local gate
  attempt lacked the notebook extra; `uv sync --extra notebook`, as CI uses, restored the expected
  environment and the complete rerun was green.
